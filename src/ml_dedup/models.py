"""Лёгкие DTO для dedup (без ORM в публичном API)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ActiveEventView:
    """Срез Event для сравнения с кандидатом."""

    id: int
    title: str
    body: str
    importance: int
    disaster_flag: bool
    address_id: int | None
    geo_by: str | None
    source: str
    source_msg_id: str | None
    source_url: str | None
    image_url: str | None
    published_at: datetime | None
    active_from: datetime | None
    active_to: datetime | None
    created_at: datetime | None
    lat: float | None = None
    lon: float | None = None
