"""HTTP-роуты событий — GET лента/карта (nearby персонально, city общий)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from events.api.deps import DbSession, get_max_user_id
from events.api.schemas import (
    FeedItemResponse,
    FeedOriginResponse,
    FeedResponse,
    MapPointResponse,
    MapResponse,
)
from events.handlers import crud
from events.models.event import Event

router = APIRouter(prefix="/events", tags=["events"])


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


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    scope: Annotated[crud.EventScope, Query()],
    session: DbSession,
    max_user_id: Annotated[int, Depends(get_max_user_id)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[
        str | None,
        Query(description="Opaque cursor с предыдущей страницы (не offset)"),
    ] = None,
) -> FeedResponse:
    """
    TikTok-лента nearby|city.

    Nearby — по выбранному дому, city — общая выдача.
    X-Max-User-Id обязателен.
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


@router.get("/map", response_model=MapResponse)
def get_map(
    session: DbSession,
    max_user_id: Annotated[int, Depends(get_max_user_id)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    after_id: Annotated[int, Query(ge=0)] = 0,
) -> MapResponse:
    """Точки карты: все события с адресом (правила importance/map)."""
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
