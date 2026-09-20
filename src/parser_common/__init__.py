"""
Общий пайплайн парсеров: ParserCandidate → EventDraft → (ml_dedup) → events.

KAN-13 = normalize/classify/time/place. KAN-19 = ml_dedup в persist_candidate.
"""

from parser_common.ingest import persist_candidate
from parser_common.models import EventDraft, ParserCandidate
from parser_common.normalize import normalize, to_event_create

__all__ = [
    "EventDraft",
    "ParserCandidate",
    "normalize",
    "to_event_create",
    "persist_candidate",
]
