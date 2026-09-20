"""Преобразование RawNewsArticle → events через parser_common."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from address.resolve import GeoBind
from address.street_catalog import StreetCatalog
from events.handlers.crud import list_existing_source_msg_ids
from events.models.event import Event, EventSource
from parse_news.models.article import RawNewsArticle
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


def article_to_candidate(
    article: RawNewsArticle,
    *,
    geo: GeoBind | None = None,
    address_id: int | None = None,
    geo_by: str | None = None,
) -> ParserCandidate:
    title = article.title
    body = clean_article_body(article.body, title=title) or ""
    raw_text = f"{title}\n{body}".strip() if body else title
    resolved_id = geo.address_id if geo is not None else address_id
    resolved_by = geo.geo_by if geo is not None else geo_by
    return ParserCandidate(
        raw_text=raw_text,
        source=EventSource.NEWS.value,
        source_msg_id=article.source_msg_id,
        title=title,
        body=body or None,
        source_url=article.url,
        image_url=article.image_url,
        address_id=resolved_id,
        geo_by=resolved_by,
        published_at=article.published_at,
    )


def persist_article(
    session: Session,
    article: RawNewsArticle,
    *,
    geo: GeoBind | None = None,
    address_id: int | None = None,
    geo_by: str | None = None,
) -> Event | None:
    existing = list_existing_source_msg_ids(
        session,
        source=EventSource.NEWS.value,
        source_msg_ids=[article.source_msg_id],
    )
    if article.source_msg_id in existing:
        logger.debug("Дубликат новости %s — пропуск", article.source_msg_id)
        return None

    candidate = article_to_candidate(
        article,
        geo=geo,
        address_id=address_id,
        geo_by=geo_by,
    )
    try:
        with session.begin_nested():
            catalog = _get_street_catalog(session) if candidate.address_id is None else None
            return persist_candidate(session, candidate, street_catalog=catalog)
    except IntegrityError:
        logger.debug("Дубликат новости %s (IntegrityError) — пропуск", article.source_msg_id)
        return None
