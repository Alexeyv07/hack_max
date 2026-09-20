"""RawMcNotice → events через parser_common; fan-out по улицам."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from address.resolve import GeoBind
from address.street_catalog import StreetCatalog
from events.handlers.crud import list_existing_source_msg_ids
from events.models.event import Event, EventSource
from parse_mc.models.notice import RawMcNotice
from parser_common.body_text import clean_article_body
from parser_common.ingest import persist_candidate
from parser_common.models.candidate import ParserCandidate
from project.logging_setup import get_logger

logger = get_logger(__name__)

_street_catalog: StreetCatalog | None = None


def _get_street_catalog(session: Session) -> StreetCatalog | None:
    global _street_catalog
    if _street_catalog is not None:
        return _street_catalog
    try:
        _street_catalog = StreetCatalog.load(session, city="Москва")
    except Exception:
        logger.exception("StreetCatalog.load failed")
        return None
    return _street_catalog


def notice_to_candidate(
    notice: RawMcNotice,
    *,
    geo: GeoBind | None = None,
    source_msg_id: str | None = None,
) -> ParserCandidate:
    title = notice.title
    body = clean_article_body(notice.body, title=title) or ""
    raw_text = f"{title}\n{body}".strip() if body else title
    return ParserCandidate(
        raw_text=raw_text,
        source=EventSource.MC.value,
        source_msg_id=source_msg_id or notice.source_msg_id,
        title=title,
        body=body or None,
        source_url=notice.url,
        image_url=notice.image_url,
        address_id=geo.address_id if geo else None,
        geo_by=geo.geo_by if geo else None,
        published_at=notice.published_at,
    )


def _msg_id_for_geo(notice: RawMcNotice, geo: GeoBind | None, *, multi: bool) -> str:
    base = notice.source_msg_id
    if not multi or geo is None:
        return base
    return f"{base}:addr:{geo.address_id}"


def persist_notice(
    session: Session,
    notice: RawMcNotice,
    *,
    geos: list[GeoBind] | None = None,
) -> list[Event]:
    """
    Создать одно или несколько событий.

    Несколько ``geos`` (разные улицы) → отдельное событие на каждую улицу
    с уникальным ``source_msg_id`` ``…:addr:{address_id}``.
    """
    binds: list[GeoBind | None] = list(geos) if geos else [None]
    multi = len([b for b in binds if b is not None]) > 1

    msg_ids = [_msg_id_for_geo(notice, g, multi=multi) for g in binds]
    existing = list_existing_source_msg_ids(
        session,
        source=EventSource.MC.value,
        source_msg_ids=msg_ids,
    )

    created: list[Event] = []
    for geo, msg_id in zip(binds, msg_ids, strict=True):
        if msg_id in existing:
            logger.debug("Дубликат УК-объявления %s — пропуск", msg_id)
            continue
        candidate = notice_to_candidate(notice, geo=geo, source_msg_id=msg_id)
        try:
            with session.begin_nested():
                catalog = _get_street_catalog(session) if candidate.address_id is None else None
                event = persist_candidate(session, candidate, street_catalog=catalog)
        except IntegrityError:
            logger.debug("Дубликат УК-объявления %s (IntegrityError) — пропуск", msg_id)
            continue
        if event is not None:
            created.append(event)
            existing.add(msg_id)
    return created
