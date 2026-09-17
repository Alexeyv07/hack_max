"""Сырая новость до normalize / persist."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RawNewsArticle:
    """Одна статья источника (ещё не Event)."""

    outlet: str
    external_id: str
    url: str
    title: str
    published_at: datetime
    body: str | None = None
    image_url: str | None = None
    # Опциональная гео-метаданные с источника (если адаптер смог вытащить).
    geo_city: str | None = None
    geo_street: str | None = None
    geo_house: str | None = None

    @property
    def source_msg_id(self) -> str:
        return f"{self.outlet}:{self.external_id}"
