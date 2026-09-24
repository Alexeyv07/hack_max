"""RawMcNotice → events через parser_common; fan-out по улицам."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from address.resolve import GeoBind
from events.handlers.crud import list_existing_source_msg_ids
from events.models.event import Event, EventSource
from parse_mc.models.notice import RawMcNotice
from parser_common.body_text import clean_article_body
from parser_common.ingest import persist_candidate
from parser_common.models.candidate import ParserCandidate
from project.logging_setup import get_logger

logger = get_logger(__name__)


def notice_to_candidate(
    notice: RawMcNotice,
    *,
    geo: GeoBind | None = None,
    source_msg_id: str | None = None,
) -> ParserCandidate:
    title = (notice.title or "").strip() or None
    body = clean_article_body(notice.body, title=title) or ""
    raw_text = "\n".join(part for part in (title, body) if part).strip() or (title or body or "")
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


def _msg_id_for_geo(notice: RawMcNotice, geo: GeoBind, *, multi: bool) -> str:
    base = notice.source_msg_id
    if not multi:
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

    Без московских привязок — не пишем (catalog не угадывает улицу).
    """
    if not geos:
        logger.info(
            "Пропуск УК-объявления без московского geo %s: %s",
            notice.source_msg_id,
            (notice.title or "")[:80],
        )
        return []

    binds = list(geos)
    multi = len(binds) > 1

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
        if candidate.address_id is None:
            continue
        try:
            with session.begin_nested():
                # geo уже из resolve_notice_geos — каталог не передаём.
                event = persist_candidate(session, candidate, street_catalog=None)
        except IntegrityError:
            logger.debug("Дубликат УК-объявления %s (IntegrityError) — пропуск", msg_id)
            continue
        if event is not None:
            created.append(event)
            existing.add(msg_id)
    return created
