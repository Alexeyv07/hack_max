"""HTTP-роуты событий — GET лента/карта (nearby персонально, city общий)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from events.api.deps import DbSession, get_max_user_id
from events.api.schemas import (
    ApiError,
    FeedItemResponse,
    FeedOriginResponse,
    FeedResponse,
    MapPointResponse,
    MapResponse,
)
from events.handlers import crud
from events.models.event import Event

router = APIRouter(prefix="/events", tags=["Events"])

_FEED_RESPONSES = {
    status.HTTP_200_OK: {
        "description": (
            "Страница ленты. Пустой `items` — валидный ответ "
            "(нет адреса, нет чата, нет событий в радиусе / по городу)."
        ),
        "model": FeedResponse,
    },
    status.HTTP_400_BAD_REQUEST: {
        "description": "Некорректные query-параметры (например, битый `cursor` или `limit`).",
        "model": ApiError,
    },
    status.HTTP_401_UNAUTHORIZED: {
        "description": "Не передан обязательный заголовок `X-Max-User-Id`.",
        "model": ApiError,
    },
    status.HTTP_422_UNPROCESSABLE_ENTITY: {
        "description": "Ошибка валидации FastAPI/Pydantic (неверный тип `scope`, `limit` вне диапазона).",
        "model": ApiError,
    },
}

_MAP_RESPONSES = {
    status.HTTP_200_OK: {
        "description": "Набор точек для полноэкранной карты webapp.",
        "model": MapResponse,
    },
    status.HTTP_400_BAD_REQUEST: {
        "description": "Некорректный `limit`.",
        "model": ApiError,
    },
    status.HTTP_401_UNAUTHORIZED: {
        "description": "Не передан обязательный заголовок `X-Max-User-Id`.",
        "model": ApiError,
    },
    status.HTTP_422_UNPROCESSABLE_ENTITY: {
        "description": "Ошибка валидации query-параметров.",
        "model": ApiError,
    },
}


def _to_feed_item(event: Event) -> FeedItemResponse:
    return FeedItemResponse(
        id=event.id,
        title=event.title,
        body=event.body,
        importance=event.importance,
        source=event.source,
        lat=event.lat,
        lon=event.lon,
        weight=event.weight,
        source_msg_id=event.source_msg_id,
        disaster_flag=event.disaster_flag,
        source_url=event.source_url,
        image_url=event.image_url,
        geo_by=event.geo_by,
        location=event.location,
        published_at=event.published_at,
        active_from=event.active_from,
        active_to=event.active_to,
        created_at=event.created_at,
        updated_at=event.updated_at,
        distance_m=event.distance_m,
        proximity=event.proximity
        if event.proximity in ("home", "block", "street", "district")
        else None,
        same_street=event.same_street,
        is_active_now=event.is_active_now,
    )


@router.get(
    "/feed",
    response_model=FeedResponse,
    summary="TikTok-лента событий (nearby | city)",
    response_description="Страница карточек, отсортированная по весу",
    responses=_FEED_RESPONSES,
)
def get_feed(
    scope: Annotated[
        crud.EventScope,
        Query(
            description=(
                "**Режим ленты**\n\n"
                "- `nearby` — персональная лента вокруг выбранного дома пользователя "
                "(нужны `X-Max-User-Id`, личный адрес или membership в домовом чате, "
                "и привязанный MAX-чат). Радиус ~6 км (`events.nearby_radius_m`). "
                "Только `geo_by` ∈ {`street`, `home`}; `home` — только свой адрес. "
                "В ответе заполняются `distance_m`, `proximity`, `same_street`, `origin`.\n\n"
                "- `city` — общая городская лента: все события с `Address.city = Москва` "
                "(любой `geo_by`). Поля расстояния / `origin` пустые.\n\n"
                "**Общие фильтры обоих режимов:** только события с `address_id` и "
                "непустым `Address.address_text`; `importance` ∈ {1, 2}; "
                "просроченные по `active_to` скрыты; дубликаты сливаются."
            ),
            examples=["nearby", "city"],
        ),
    ],
    session: DbSession,
    max_user_id: Annotated[int, Depends(get_max_user_id)],
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=50,
            description=("Размер страницы (1–50). Типичное значение для snap-ленты webapp — `20`."),
            examples=[20],
        ),
    ] = 20,
    cursor: Annotated[
        str | None,
        Query(
            description=(
                "Непрозрачный **keyset-курсор** с предыдущей страницы "
                "(`FeedResponse.next_cursor`). Это **не** offset и не page number: "
                "курсор кодирует пару `(weight, id)` и продолжает выдачу строго после неё. "
                "Не смешивай курсоры разных `scope`. "
                "Пропусти или передай `null` для первой страницы."
            ),
            examples=["eyJ3ZWlnaHQiOjAuODEyLCJldmVudF9pZCI6MTA0Mn0"],
        ),
    ] = None,
) -> FeedResponse:
    """
    Вертикальная лента webapp «Умный город» (канва TikTok).

    ### Идентификация
    Обязателен заголовок **`X-Max-User-Id`**: ID пользователя Max
    (`initDataUnsafe.user.id` из Bridge; локально для отладки — фиксированный id).

    ### Nearby (`scope=nearby`)
    1. Берётся личный адрес пользователя (`users.address_id`), если он привязан
       к реальному домовому чату; иначе — legacy memberships.
    2. Без выбранного адреса / без linked group → пустой `items`, `origin=null`.
    3. Кандидаты в bbox + haversine ≤ `nearby_radius_m` (~6000 м).
    4. Ранжирование: вес события + бусты `same_street` / активного окна времени.
    5. В ответе — `origin` с координатами дома и радиусом.

    ### City (`scope=city`)
    Общая выдача по Москве; персонализация по дому не применяется.
    Заголовок `X-Max-User-Id` всё равно обязателен (контракт webapp).

    ### Пагинация
    Передавай `next_cursor` как `cursor` со **тем же** `scope` и желательно тем же `limit`,
    пока `next_cursor` не станет `null`.

    ### Запись
    HTTP API **только читает**. Создание/обновление событий — in-process handlers
    парсеров и бота, не через эти ручки.
    """
    try:
        page = crud.list_feed(
            session,
            scope=scope,
            limit=limit,
            cursor=cursor,
            max_user_id=max_user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    origin = None
    if page.origin is not None:
        origin = FeedOriginResponse(
            lat=page.origin.lat,
            lon=page.origin.lon,
            radius_m=page.origin.radius_m,
            chat_count=page.origin.chat_count,
        )

    return FeedResponse(
        items=[_to_feed_item(item) for item in page.items],
        scope=page.scope.value,
        next_cursor=page.next_cursor,
        count=len(page.items),
        origin=origin,
    )


@router.get(
    "/map",
    response_model=MapResponse,
    summary="Точки событий для карты",
    response_description="Маркеры с категорией иконки для Yandex Maps",
    responses=_MAP_RESPONSES,
)
def get_map(
    session: DbSession,
    max_user_id: Annotated[int, Depends(get_max_user_id)],
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=1000,
            description=(
                "Максимум точек в ответе (1–1000). "
                "По умолчанию `500` — комфортно для одного viewport Москвы."
            ),
            examples=[500],
        ),
    ] = 500,
    after_id: Annotated[int, Query(ge=0)] = 0,
) -> MapResponse:
    """
    Полный набор точек для экрана карты webapp (кнопка «Карт» на карточке ленты).

    ### Что попадает на карту
    - События с адресом и непустым `address_text`;
    - `importance` ∈ {1, 2} (бытовуха `3` отсекается);
    - `geo_by` ∈ {`street`, `home`};
    - не просроченные по `active_to`;
    - дополнительно фильтр `allowed_on_map` (катастрофы / важное).

    ### Иконки
    Поле `category`:
    - `catastrophe` — ЧС (`disaster_flag`) или высокий приоритет (`importance=1`);
    - `important` — обычное важное (`importance=2`).

    ### Персонализация
    Выдача **общая для всех** пользователей (не зависит от дома).
    `X-Max-User-Id` обязателен по контракту webapp, но на выборку не влияет.

    ### Координаты
    Для `geo_by=street` lat/lon — **центр улицы** (среднее по домам каталога),
    а не случайный номер дома.
    """
    _ = max_user_id
    try:
        points, next_after_id = crud.list_map_page(session, limit=limit, after_id=after_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return MapResponse(
        items=[
            MapPointResponse(
                id=point.id,
                title=point.title,
                lat=point.lat,
                lon=point.lon,
                importance=point.importance,
                category=point.category,
                disaster_flag=point.disaster_flag,
                body=point.body,
                geo_by=point.geo_by,
                location=point.location,
            )
            for point in points
        ],
        count=len(points),
        next_after_id=next_after_id,
    )
