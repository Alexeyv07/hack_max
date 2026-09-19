"""Сырое объявление УК / ЖЭК до normalize / persist."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RawMcNotice:
    """Одно объявление управляющей компании (ещё не Event)."""

    outlet: str
    external_id: str
    url: str
    title: str
    published_at: datetime
    body: str | None = None
    image_url: str | None = None
    # Явные улицы с карточки (если адаптер вытащил список адресов).
    streets: tuple[str, ...] = field(default_factory=tuple)
    geo_city: str | None = None
    geo_street: str | None = None
    geo_house: str | None = None

    @property
    def source_msg_id(self) -> str:
        return f"{self.outlet}:{self.external_id}"
