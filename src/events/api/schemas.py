"""Pydantic-схемы HTTP API событий (только чтение для webapp)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiError(BaseModel):
    """Стандартная ошибка FastAPI (`HTTPException.detail`)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"detail": "Нужен заголовок X-Max-User-Id"},
                {"detail": "limit должен быть >= 1"},
            ]
        }
    )

    detail: str = Field(
        description="Человекочитаемое описание ошибки (русский текст).",
        examples=["Нужен заголовок X-Max-User-Id"],
    )


class FeedItemResponse(BaseModel):
    """Одна карточка TikTok-ленты (`GET /events/feed`)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": 1042,
                    "title": "Отключение горячей воды на Варшавском шоссе",
                    "body": (
                        "С 10:00 до 18:00 плановые работы на теплосети. "
                        "Затронуты дома 12–28 по Варшавскому шоссе."
                    ),
                    "importance": 2,
                    "source": "mc",
                    "lat": 55.65321,
                    "lon": 37.62014,
                    "weight": 0.812,
                    "source_msg_id": "moek:outage:2026-03-12:addr:881",
                    "disaster_flag": False,
                    "source_url": "https://www.moek.ru/press/...",
                    "image_url": None,
                    "geo_by": "street",
                    "location": "Москва, Варшавское шоссе",
                    "published_at": "2026-03-11T09:15:00+00:00",
                    "active_from": "2026-03-12T07:00:00+00:00",
                    "active_to": "2026-03-12T15:00:00+00:00",
                    "created_at": "2026-03-11T09:20:11+00:00",
                    "updated_at": "2026-03-11T09:20:11+00:00",
                    "distance_m": 420.5,
                    "proximity": "block",
                    "same_street": True,
                    "is_active_now": True,
                }
            ]
        }
    )

    id: int = Field(
        description="Внутренний ID события в таблице `events`.",
        examples=[1042],
        ge=1,
    )
    title: str | None = Field(
        default=None,
        description=(
            "Короткий заголовок карточки. "
            "`null` — у источника не удалось выделить title: в UI показывай `body` как основной текст."
        ),
        examples=["Отключение горячей воды на Варшавском шоссе"],
    )
    body: str = Field(
        description="Полный текст события (описание / тело новости). Всегда непустая строка.",
        examples=["С 10:00 до 18:00 плановые работы на теплосети. Затронуты дома 12–28."],
        min_length=1,
    )
    importance: int = Field(
        description=(
            "Приоритет события (ML classify):\n"
            "- `1` — высокий (аварии, ЧС, срочное);\n"
            "- `2` — важное (отключения, ремонты, значимые городские новости);\n"
            "- `3` — бытовуха — **в ленту не попадает**.\n\n"
            "В ответе feed всегда `1` или `2`."
        ),
        examples=[2],
        ge=1,
        le=2,
    )
    source: str = Field(
        description=(
            "Код источника события:\n"
            "- `neighbors_chat` — сообщение из домового чата соседей;\n"
            "- `news` — новостные СМИ (ТАСС, РИА, Коммерсант, m24, …);\n"
            "- `mc` — УК / ЖЭК / МОЭК (KAN-28);\n"
            "- `max_public` — паблики Max;\n"
            "- `manual` — ручное создание."
        ),
        examples=["mc", "news", "neighbors_chat"],
    )
    lat: float | None = Field(
        description=(
            "Широта точки на карте/превью (из `addresses`). "
            "Для `geo_by=street` — центр улицы (avg домов), не случайный дом. "
            "`null` теоретически возможен только при битых данных; в ленте обычно задан."
        ),
        examples=[55.65321],
    )
    lon: float | None = Field(
        description="Долгота точки (см. `lat`).",
        examples=[37.62014],
    )
    weight: float = Field(
        description=(
            "Ранг карточки в ленте (больше = выше). "
            "База: `0.5×relevance + 0.3×timeliness + 0.2×source_reliability`, "
            "затем бусты nearby (`same_street`, активное окно `active_from`/`active_to`). "
            "Курсор пагинации строится по паре `(weight, id)`."
        ),
        examples=[0.812],
        ge=0,
    )
    source_msg_id: str | None = Field(
        default=None,
        description=(
            "Стабильный ID сообщения/статьи у источника "
            "(уникальность вместе с `source` в БД). "
            "Для MC fan-out может содержать суффикс `:addr:{address_id}`."
        ),
        examples=["moek:outage:2026-03-12:addr:881"],
    )
    disaster_flag: bool = Field(
        description=(
            "Признак чрезвычайной ситуации (отдельно от `importance`). "
            "На фронте — спец. SVG/акцент. Не алиас класса `1`."
        ),
        examples=[False],
    )
    source_url: str | None = Field(
        default=None,
        description="URL первоисточника (статья / объявление). `null` — ссылку в UI не показывать.",
        examples=["https://www.moek.ru/press/..."],
    )
    image_url: str | None = Field(
        description=(
            "URL главной фотографии события. "
            "`null` → фронт рисует чёрный плейсхолдер или карту-превью с меткой."
        ),
        examples=[None],
    )
    geo_by: Literal["city", "street", "home"] | None = Field(
        default=None,
        description=(
            "Точность геопривязки:\n"
            "- `city` — уровень города (Москва);\n"
            "- `street` — улица / район улицы;\n"
            "- `home` — конкретный дом.\n\n"
            "В **nearby** в ленту попадают только `street`|`home` "
            "(`home` — только если это выбранный адрес пользователя)."
        ),
        examples=["street"],
    )
    location: str | None = Field(
        default=None,
        description=(
            "Человекочитаемый адрес (`Address.address_text`) для подписи под карточкой. "
            "События без непустого `address_text` в ленту не попадают."
        ),
        examples=["Москва, Варшавское шоссе"],
    )
    published_at: datetime | None = Field(
        default=None,
        description=(
            "Время публикации у источника (RSS/`published`). "
            "Если `null`, для UI/свежести ориентируйся на `created_at`."
        ),
        examples=["2026-03-11T09:15:00+00:00"],
    )
    active_from: datetime | None = Field(
        default=None,
        description=(
            "Начало окна действия события (ML time-window). "
            "`null` — начало неизвестно / не извлечено."
        ),
        examples=["2026-03-12T07:00:00+00:00"],
    )
    active_to: datetime | None = Field(
        default=None,
        description=(
            "Конец окна действия. "
            "События с `active_to` в прошлом **скрыты** из ленты и карты. "
            "`null` — ещё актуально или конец неизвестен."
        ),
        examples=["2026-03-12T15:00:00+00:00"],
    )
    created_at: datetime | None = Field(
        default=None,
        description="Момент создания записи в БД.",
        examples=["2026-03-11T09:20:11+00:00"],
    )
    updated_at: datetime | None = Field(
        default=None,
        description="Момент последнего обновления (в т.ч. после dedup UPDATE).",
        examples=["2026-03-11T09:20:11+00:00"],
    )
    distance_m: float | None = Field(
        default=None,
        description=(
            "Haversine-расстояние в метрах от выбранного дома пользователя до точки события. "
            "Заполняется **только** для `scope=nearby`; для `city` всегда `null`."
        ),
        examples=[420.5],
        ge=0,
    )
    proximity: Literal["home", "block", "street", "district"] | None = Field(
        default=None,
        description=(
            "Дискретный пояс близости (только nearby), по `distance_m`:\n"
            "- `home` — ≤ 250 м;\n"
            "- `block` — ≤ 800 м;\n"
            "- `street` — ≤ 1.5 км;\n"
            "- `district` — дальше, но в пределах `nearby_radius_m` (~6 км).\n\n"
            "Для city — `null`."
        ),
        examples=["block"],
    )
    same_street: bool = Field(
        default=False,
        description=(
            "`true`, если улица события совпадает с улицей выбранного дома пользователя "
            "(буст веса в nearby). Для city обычно `false`."
        ),
        examples=[True],
    )
    is_active_now: bool | None = Field(
        default=None,
        description=(
            "Попадает ли текущий момент в окно `[active_from, active_to]`:\n"
            "- `true` — событие сейчас «в силе» (буст в ранжировании);\n"
            "- `false` — вне окна (просроченные с известным `active_to` уже отфильтрованы);\n"
            "- `null` — окно не задано / недостаточно данных."
        ),
        examples=[True],
    )


class FeedOriginResponse(BaseModel):
    """Точка отсчёта для персональной nearby-ленты."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "lat": 55.65012,
                    "lon": 37.61890,
                    "radius_m": 6000,
                    "chat_count": 0,
                }
            ]
        }
    )

    lat: float = Field(
        description="Широта выбранного дома / точки nearby.",
        examples=[55.65012],
    )
    lon: float = Field(
        description="Долгота выбранного дома / точки nearby.",
        examples=[37.61890],
    )
    radius_m: float = Field(
        description=(
            "Радиус отсечения кандидатов в метрах "
            "(`events.nearby_radius_m`, по умолчанию 6000). "
            "События дальше не попадают в nearby."
        ),
        examples=[6000],
        gt=0,
    )
    chat_count: int = Field(
        description=(
            "Сколько реальных домовых чатов участвует в поиске. "
            "`0` — лента строится только по личному адресу пользователя "
            "(`users.address_id`), без группового чата."
        ),
        examples=[0],
        ge=0,
    )


class FeedResponse(BaseModel):
    """Страница ленты событий."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [],
                    "scope": "nearby",
                    "next_cursor": "eyJ3ZWlnaHQiOjAuODEyLCJldmVudF9pZCI6MTA0Mn0",
                    "count": 0,
                    "origin": {
                        "lat": 55.65012,
                        "lon": 37.61890,
                        "radius_m": 6000,
                        "chat_count": 0,
                    },
                }
            ]
        }
    )

    items: list[FeedItemResponse] = Field(
        description=(
            "Карточки текущей страницы, уже отсортированные по убыванию `weight`, затем `id`. "
            "Пустой список — нормальный ответ: нет адреса / нет чата / нет событий в радиусе."
        ),
    )
    scope: Literal["nearby", "city"] = Field(
        description="Фактический scope ответа (эхо запроса).",
        examples=["nearby"],
    )
    next_cursor: str | None = Field(
        default=None,
        description=(
            "Непрозрачный keyset-курсор для следующей страницы. "
            "Передай его как `cursor` в следующем запросе **с тем же** `scope`. "
            "`null` — это последняя страница (или пустая выдача)."
        ),
        examples=["eyJ3ZWlnaHQiOjAuODEyLCJldmVudF9pZCI6MTA0Mn0"],
    )
    count: int = Field(
        description="Число элементов в `items` (не total по БД).",
        examples=[20],
        ge=0,
    )
    origin: FeedOriginResponse | None = Field(
        default=None,
        description=(
            "Гео-контекст nearby. "
            "`null` если `scope=city`, либо у пользователя нет выбранного адреса / "
            "нет привязанного домового чата (тогда `items` пустой)."
        ),
    )


class MapPointResponse(BaseModel):
    """Точка на полноэкранной карте (`GET /events/map`)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": 1042,
                    "title": "Отключение горячей воды",
                    "lat": 55.65321,
                    "lon": 37.62014,
                    "importance": 2,
                    "category": "important",
                    "disaster_flag": False,
                    "body": "С 10:00 до 18:00 плановые работы на теплосети.",
                    "geo_by": "street",
                    "location": "Москва, Варшавское шоссе",
                }
            ]
        }
    )

    id: int = Field(
        description="ID события (= id в ленте).",
        examples=[1042],
        ge=1,
    )
    title: str | None = Field(
        description="Подпись маркера. `null` — можно взять начало `body`.",
        examples=["Отключение горячей воды"],
    )
    lat: float = Field(
        description="Широта маркера (для street — центр улицы).",
        examples=[55.65321],
    )
    lon: float = Field(
        description="Долгота маркера.",
        examples=[37.62014],
    )
    importance: int = Field(
        description="Приоритет `1`|`2` (бытовуха `3` на карту не попадает).",
        examples=[2],
        ge=1,
        le=2,
    )
    category: Literal["catastrophe", "important"] = Field(
        description=(
            "Код иконки/цвета для Yandex Maps JS API:\n"
            "- `catastrophe` — `disaster_flag=true` или `importance=1`;\n"
            "- `important` — `importance=2`."
        ),
        examples=["important"],
    )
    disaster_flag: bool = Field(
        description="Признак ЧС (см. ленту).",
        examples=[False],
    )
    body: str | None = Field(
        default=None,
        description="Краткое описание для балуна / bottom sheet на карте.",
        examples=["С 10:00 до 18:00 плановые работы на теплосети."],
    )
    geo_by: Literal["city", "street", "home"] | None = Field(
        default=None,
        description=(
            "Точность гео. На карте сейчас отдаются точки с `geo_by` ∈ {`street`, `home`}."
        ),
        examples=["street"],
    )
    location: str | None = Field(
        default=None,
        description="Текст адреса для подписи.",
        examples=["Москва, Варшавское шоссе"],
    )


class MapResponse(BaseModel):
    """Набор точек карты."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [],
                    "count": 0,
                }
            ]
        }
    )

    items: list[MapPointResponse] = Field(
        description=(
            "Точки в порядке `importance ASC`, затем `id ASC` "
            "(сначала катастрофы/высокий приоритет)."
        ),
    )
    count: int = Field(
        description="Число точек в `items`.",
        examples=[42],
        ge=0,
    )


class HealthResponse(BaseModel):
    """Ответ liveness-проверки."""

    model_config = ConfigDict(json_schema_extra={"examples": [{"status": "ok"}]})

    status: Literal["ok"] = Field(
        description="Всегда `ok`, если процесс API отвечает.",
        examples=["ok"],
    )
