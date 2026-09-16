"""
Общий пайплайн парсеров: ParserCandidate → EventDraft → (воркер) → events.

KAN-13 = библиотека normalize/classify/geo. Запись в БД и fetch источников —
в воркерах KAN-10/11/12 через ``persist_candidate`` / ``create_event``.
Дедуп — KAN-19.

См. README.md в этом пакете и ml/classify/MODEL.md.
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
