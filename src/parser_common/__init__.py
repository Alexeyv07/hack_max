"""Общий пайплайн парсеров: ParserCandidate → EventDraft (без дедупа)."""

from parser_common.models import EventDraft, ParserCandidate
from parser_common.normalize import normalize, to_event_create

__all__ = [
    "EventDraft",
    "ParserCandidate",
    "normalize",
    "to_event_create",
]
