"""
Общий пайплайн парсеров: ParserCandidate → EventDraft.

См. classify.py (каскад ML) и ml/classify/MODEL.md (обучение).
Дедуп — KAN-19, не этот пакет.
"""

from parser_common.models import EventDraft, ParserCandidate
from parser_common.normalize import normalize, to_event_create

__all__ = [
    "EventDraft",
    "ParserCandidate",
    "normalize",
    "to_event_create",
]
