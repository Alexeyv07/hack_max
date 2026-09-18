"""HTTP-роуты событий — GET по пользователю и его чатам (без lat/lon/radius в query)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from events.api.deps import DbSession, get_user_memberships
from events.api.schemas import (
    FeedItemResponse,
    FeedResponse,
    MapPointResponse,
    MapResponse,
)
from events.handlers import crud
from events.models.event import Event
from user_chat.models.membership import ChatMembership

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
        created_at=event.created_at,
        updated_at=event.updated_at,
        distance_m=event.distance_m,
    )


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    scope: Annotated[crud.EventScope, Query()],
    session: DbSession,
    memberships: Annotated[list[ChatMembership], Depends(get_user_memberships)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[
        str | None,
        Query(description="Opaque cursor с предыдущей страницы (не offset)"),
    ] = None,
) -> FeedResponse:
    """TikTok-лента nearby|city: гео из чатов пользователя (X-Max-User-Id)."""
    try:
        page = crud.list_feed(
            session,
            scope=scope,
            memberships=memberships,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return FeedResponse(
        items=[_to_feed_item(item) for item in page.items],
        scope=page.scope.value,
        next_cursor=page.next_cursor,
        count=len(page.items),
    )


@router.get("/map", response_model=MapResponse)
def get_map(
    session: DbSession,
    memberships: Annotated[list[ChatMembership], Depends(get_user_memberships)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> MapResponse:
    """Точки карты по чатам пользователя: title, importance, category для Yandex."""
    try:
        points = crud.list_map_points(
            session,
            memberships=memberships,
            limit=limit,
        )
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
            )
            for point in points
        ],
        count=len(points),
    )
