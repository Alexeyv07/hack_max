"""Преобразование RawNewsArticle → events через parser_common."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from address.resolve import GeoBind
from events.handlers.crud import list_existing_source_msg_ids
from events.models.event import Event, EventSource
from parse_news.models.article import RawNewsArticle
from parser_common.body_text import clean_article_body
from parser_common.ingest import persist_candidate
from parser_common.models.candidate import ParserCandidate
from project.logging_setup import get_logger

logger = get_logger(__name__)


def article_to_candidate(
    article: RawNewsArticle,
    *,
    geo: GeoBind | None = None,
    address_id: int | None = None,
    geo_by: str | None = None,
) -> ParserCandidate:
    title = (article.title or "").strip() or None
    body = clean_article_body(article.body, title=title) or ""
    raw_text = "\n".join(part for part in (title, body) if part).strip() or (title or body or "")
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
    # Без московского адреса не пишем: place_ner/catalog не должен «угадывать» улицу.
    if candidate.address_id is None:
        logger.info(
            "Пропуск новости без московского geo %s: %s",
            article.source_msg_id,
            (article.title or "")[:80],
        )
        return None

    try:
        with session.begin_nested():
            # address_id уже задан resolve_article_geo — каталог не передаём.
            return persist_candidate(session, candidate, street_catalog=None)
    except IntegrityError:
        logger.debug("Дубликат новости %s (IntegrityError) — пропуск", article.source_msg_id)
        return None
