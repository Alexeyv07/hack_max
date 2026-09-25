"""Pydantic-схемы HTTP API событий (только чтение для webapp)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class FeedItemResponse(BaseModel):
    id: int
    title: str | None = Field(
        default=None,
        description="Заголовок; null — показывай body как основной текст",
    )
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
        description="Главная фото; null → фронт ставит чёрный плейсхолдер / карту",
    )
    geo_by: str | None = Field(
        default=None,
        description="Точность гео: city | street | home",
    )
    location: str | None = Field(
        default=None,
        description="Текст адреса события (Address.address_text)",
    )
    published_at: datetime | None = Field(
        default=None,
        description="Время публикации у источника; иначе смотри created_at",
    )
    active_from: datetime | None = Field(
        default=None,
        description="Начало действия события (если извлечено)",
    )
    active_to: datetime | None = Field(
        default=None,
        description="Конец действия; null = ещё актуально / неизвестно",
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None
    distance_m: float | None = Field(
        default=None,
        description="Haversine до выбранного дома пользователя (только nearby)",
    )
    proximity: Literal["home", "block", "street", "district"] | None = Field(
        default=None,
        description="Порядок близости: home≤250м, block≤800м, street≤1.5км, иначе district",
    )
    same_street: bool = Field(
        default=False,
        description="Улица события совпадает с улицей выбранного дома пользователя",
    )
    is_active_now: bool | None = Field(
        default=None,
        description="Окно active_from/active_to: True сейчас, False вне окна, None неизвестно",
    )


class FeedOriginResponse(BaseModel):
    lat: float
    lon: float
    radius_m: float = Field(description="Откидываем события дальше этого радиуса (м)")
    chat_count: int = Field(description="Сколько чатов участвует в поиске: 0 для личного адреса")


class FeedResponse(BaseModel):
    items: list[FeedItemResponse]
    scope: Literal["nearby", "city"]
    next_cursor: str | None = None
    count: int
    origin: FeedOriginResponse | None = Field(
        default=None,
        description="Точка дома для nearby; null если адрес не выбран или scope=city",
    )


class MapPointResponse(BaseModel):
    id: int
    title: str | None = Field(description="Имя/заголовок для подписи на карте")
    lat: float
    lon: float
    importance: int
    category: str = Field(
        description="Код иконки для Yandex: catastrophe | important",
    )
    disaster_flag: bool
    body: str | None = None
    geo_by: str | None = Field(default=None, description="Точность гео: city | street | home")
    location: str | None = None


class MapResponse(BaseModel):
    items: list[MapPointResponse]
    count: int
    next_after_id: int | None = None
