"""Persist: ParserCandidate → events (вызов из воркеров парсеров)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from address.geocoding import GeoMatcher
from events.handlers.crud import create_event
from events.models.event import Event
from parser_common.models.candidate import ParserCandidate
from parser_common.normalize import normalize, to_event_create


def persist_candidate(
    session: Session,
    candidate: ParserCandidate,
    *,
    geo_matcher: GeoMatcher | None = None,
    chat_coordinates: tuple[Decimal, Decimal] | None = None,
) -> Event:
    """
    Сквозной шаг для KAN-10/11/12:

      ParserCandidate → normalize → to_event_create → create_event

    Дедуп (KAN-19) — позже внутри ``create_event`` или перед ним; этот хелпер
    не дублирует merge-логику.
    """
    draft = normalize(
        candidate,
        geo_matcher=geo_matcher,
        chat_coordinates=chat_coordinates,
    )
    return create_event(session, to_event_create(draft))
