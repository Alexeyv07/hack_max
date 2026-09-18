"""Доменные представления событий (не ORM)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class EventSource(StrEnum):
    """Источник события."""

    NEIGHBORS_CHAT = "neighbors_chat"
    NEWS = "news"
    MAX_PUBLIC = "max_public"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class EventCreate:
    """Данные для создания события (уже финальные поля, не draft парсера)."""

    title: str
    body: str
    importance: int
    source: EventSource | str
    address_id: int | None = None
    geo_by: str | None = None
    source_msg_id: str | None = None
    disaster_flag: bool = False
    source_url: str | None = None
    # Одна главная фотка (выбранная у кандидатов). None → фронт рисует карту с меткой.
    image_url: str | None = None
    published_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EventUpdate:
    """Частичное обновление события (None = не менять)."""

    title: str | None = None
    body: str | None = None
    importance: int | None = None
    source: EventSource | str | None = None
    address_id: int | None = None
    geo_by: str | None = None
    source_msg_id: str | None = None
    disaster_flag: bool | None = None
    source_url: str | None = None
    image_url: str | None = None
    published_at: datetime | None = None
    clear_address: bool = False
    clear_image: bool = False


@dataclass(slots=True)
class Event:
    """Событие на уровне приложения."""

    id: int
    title: str
    body: str
    importance: int
    source: str
    address_id: int | None
    lat: float | None
    lon: float | None
    weight: float
    source_msg_id: str | None
    disaster_flag: bool
    source_url: str | None
    image_url: str | None
    geo_by: str | None = None
    published_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    distance_m: float | None = None
