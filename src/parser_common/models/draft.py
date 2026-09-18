"""Выход parser_common до записи в events / ml_dedup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class EventDraft:
    """Нормализованный черновик события (ещё не Event в БД)."""

    title: str
    body: str
    importance: int
    source: str
    disaster_flag: bool = False
    address_id: int | None = None
    geo_by: str | None = None
    source_msg_id: str | None = None
    source_url: str | None = None
    image_url: str | None = None
    published_at: datetime | None = None
    geo_scope: str | None = None
    geo_method: str | None = None
