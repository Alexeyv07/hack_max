"""Persist: ParserCandidate → normalize → ml_dedup → events."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from address.geocoding import GeoMatcher
from address.street_catalog import StreetCatalog
from events.models.event import Event
from ml_dedup.resolve import DedupConfig, resolve_draft
from parser_common.models.candidate import ParserCandidate
from parser_common.normalize import normalize


def persist_candidate(
    session: Session,
    candidate: ParserCandidate,
    *,
    geo_matcher: GeoMatcher | None = None,
    street_catalog: StreetCatalog | None = None,
    chat_coordinates: tuple[Decimal, Decimal] | None = None,
    dedup: bool = True,
    dedup_config: DedupConfig | None = None,
    spacy_model: str = "ru_core_news_md",
) -> Event:
    """
    Сквозной шаг для KAN-10/11/12/28:

      ParserCandidate → normalize → (ml_dedup) → create|update|noop→existing

    ``dedup=False`` — всегда create (тесты / seed без merge).
    """
    draft = normalize(
        candidate,
        geo_matcher=geo_matcher,
        street_catalog=street_catalog,
        chat_coordinates=chat_coordinates,
        spacy_model=spacy_model,
    )
    if not dedup:
        from events.handlers.crud import create_event
        from parser_common.normalize import to_event_create

        return create_event(session, to_event_create(draft))

    _decision, event = resolve_draft(session, draft, config=dedup_config)
    assert event is not None
    return event
