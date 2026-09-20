"""
normalize(ParserCandidate) → EventDraft.

Шаги:
  1) title/body — ``text.build_title_and_body`` (не ML)
  2) importance — ``classify.classify_importance`` (каскад ONNX→rules)
  3) active_from/to — ``time_extract.extract_active_window`` (только ML ONNX)
  4) geo — candidate.address_id → place_ner (spaCy+StreetCatalog) → GeoMatcher

Запись в ``events`` — ``persist_candidate`` (с KAN-19 dedup) или
``to_event_create`` + ``create_event``.
"""

from __future__ import annotations

from decimal import Decimal

from address.geocoding import GeoMatcher
from address.street_catalog import StreetCatalog
from events.models.event import EventCreate
from parser_common.classify import classify_importance
from parser_common.models.candidate import ParserCandidate
from parser_common.models.draft import EventDraft
from parser_common.place_ner import resolve_place_to_address
from parser_common.text import build_title_and_body
from parser_common.time_extract import extract_active_window
from project.logging_setup import get_logger

logger = get_logger(__name__)


def normalize(
    candidate: ParserCandidate,
    *,
    geo_matcher: GeoMatcher | None = None,
    street_catalog: StreetCatalog | None = None,
    chat_coordinates: tuple[Decimal, Decimal] | None = None,
    spacy_model: str = "ru_core_news_md",
) -> EventDraft:
    if not candidate.source or not str(candidate.source).strip():
        raise ValueError("source обязателен")

    title, body = build_title_and_body(
        raw_text=candidate.raw_text,
        title=candidate.title,
        body=candidate.body,
    )
    full_text = f"{title}\n{body}\n{candidate.raw_text}"
    classified = classify_importance(full_text)

    time_win = extract_active_window(
        full_text,
        reference=candidate.published_at,
    )

    address_id = candidate.address_id
    geo_by = candidate.geo_by
    geo_scope: str | None = None
    geo_method: str | None = None

    if address_id is None:
        place_enabled = True
        model_name = spacy_model
        try:
            from project.config import get_settings

            enrich = get_settings().ml_enrich
            place_enabled = enrich.place_enabled
            model_name = enrich.spacy_model or spacy_model
        except Exception:
            pass

        place = None
        if place_enabled:
            place = resolve_place_to_address(
                candidate.geo_text or title or candidate.raw_text,
                street_catalog=street_catalog,
                geo_matcher=geo_matcher,
                spacy_model=model_name,
            )
        if place is not None:
            address_id = place.address_id
            if geo_by is None:
                geo_by = place.geo_by
            geo_method = place.method
            geo_scope = "address" if place.geo_by == "home" else place.geo_by
            logger.debug(
                "place resolve method=%s address_id=%s geo_by=%s span=%s",
                place.method,
                place.address_id,
                place.geo_by,
                place.span,
            )
        elif geo_matcher is not None:
            geo_text = candidate.geo_text or candidate.title or candidate.raw_text
            geo = geo_matcher.resolve(geo_text, chat_coordinates=chat_coordinates)
            address_id = geo.address_id
            geo_scope = geo.scope
            geo_method = geo.method
            if address_id is not None and geo_by is None:
                geo_by = "home" if geo.scope == "address" else None
            logger.debug(
                "geo resolve method=%s scope=%s address_id=%s geo_by=%s",
                geo.method,
                geo.scope,
                geo.address_id,
                geo_by,
            )

    return EventDraft(
        title=title,
        body=body,
        importance=classified.importance,
        source=str(candidate.source).strip(),
        disaster_flag=classified.disaster_flag,
        address_id=address_id,
        geo_by=geo_by,
        source_msg_id=candidate.source_msg_id,
        source_url=candidate.source_url,
        image_url=candidate.image_url,
        published_at=candidate.published_at,
        active_from=time_win.active_from,
        active_to=time_win.active_to,
        geo_scope=geo_scope,
        geo_method=geo_method,
    )


def to_event_create(draft: EventDraft) -> EventCreate:
    """Мост в ``events.handlers.create_event``. Dedup — в ``persist_candidate``."""
    return EventCreate(
        title=draft.title,
        body=draft.body,
        importance=draft.importance,
        source=draft.source,
        address_id=draft.address_id,
        geo_by=draft.geo_by,
        source_msg_id=draft.source_msg_id,
        disaster_flag=draft.disaster_flag,
        source_url=draft.source_url,
        image_url=draft.image_url,
        published_at=draft.published_at,
        active_from=draft.active_from,
        active_to=draft.active_to,
    )
