"""Pydantic-схемы HTTP API событий (только чтение для webapp)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class FeedItemResponse(BaseModel):
    id: int
    title: str
    body: str
    importance: int
    source: str
    lat: float | None
    lon: float | None
    weight: float
    source_msg_id: str | None
    disaster_flag: bool
    source_url: str | None
    image_url: str | None = Field(
        description="Главная фото; null → фронт ставит превью карты с меткой",
    )
    geo_by: str | None = Field(
        default=None,
        description="Точность гео: city | street | home",
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None
    distance_m: float | None = None


class FeedResponse(BaseModel):
    items: list[FeedItemResponse]
    scope: Literal["nearby", "city"]
    next_cursor: str | None = None
    count: int


class MapPointResponse(BaseModel):
    id: int
    title: str = Field(description="Имя/заголовок для подписи на карте")
    lat: float
    lon: float
    importance: int
    category: str = Field(
        description="Код иконки для Yandex: catastrophe | important",
    )
    disaster_flag: bool
    body: str | None = None


class MapResponse(BaseModel):
    items: list[MapPointResponse]
    count: int
