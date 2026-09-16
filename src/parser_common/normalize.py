"""
normalize(ParserCandidate) → EventDraft.

Шаги:
  1) title/body — ``text.build_title_and_body`` (не ML)
  2) importance — ``classify.classify_importance`` (каскад ONNX→rules)
  3) geo — опционально ``address.geocoding.GeoMatcher`` (не ML)

Дедуп пересекающихся событий — KAN-19, не здесь.
"""

from __future__ import annotations

from decimal import Decimal

from address.geocoding import GeoMatcher
from events.models.event import EventCreate
from parser_common.classify import classify_importance
from parser_common.models.candidate import ParserCandidate
from parser_common.models.draft import EventDraft
from parser_common.text import build_title_and_body
from project.logging_setup import get_logger

logger = get_logger(__name__)


def normalize(
    candidate: ParserCandidate,
    *,
    geo_matcher: GeoMatcher | None = None,
    chat_coordinates: tuple[Decimal, Decimal] | None = None,
) -> EventDraft:
    if not candidate.source or not str(candidate.source).strip():
        raise ValueError("source обязателен")

    title, body = build_title_and_body(
        raw_text=candidate.raw_text,
        title=candidate.title,
        body=candidate.body,
    )
    classified = classify_importance(f"{title}\n{body}\n{candidate.raw_text}")

    address_id = candidate.address_id
    geo_scope: str | None = None
    geo_method: str | None = None

    if address_id is None and geo_matcher is not None:
        geo_text = candidate.geo_text or candidate.title or candidate.raw_text
        geo = geo_matcher.resolve(geo_text, chat_coordinates=chat_coordinates)
        address_id = geo.address_id
        geo_scope = geo.scope
        geo_method = geo.method
        logger.debug(
            "geo resolve method=%s scope=%s address_id=%s",
            geo.method,
            geo.scope,
            geo.address_id,
        )

    return EventDraft(
        title=title,
        body=body,
        importance=classified.importance,
        source=str(candidate.source).strip(),
        disaster_flag=classified.disaster_flag,
        address_id=address_id,
        source_msg_id=candidate.source_msg_id,
        source_url=candidate.source_url,
        image_url=candidate.image_url,
        geo_scope=geo_scope,
        geo_method=geo_method,
    )


def to_event_create(draft: EventDraft) -> EventCreate:
    """Мост в ``events.handlers.create_event`` (после optional ml_dedup)."""
    return EventCreate(
        title=draft.title,
        body=draft.body,
        importance=draft.importance,
        source=draft.source,
        address_id=draft.address_id,
        source_msg_id=draft.source_msg_id,
        disaster_flag=draft.disaster_flag,
        source_url=draft.source_url,
        image_url=draft.image_url,
    )
