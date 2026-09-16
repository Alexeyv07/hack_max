"""CRUD (in-process) и выборки для webapp: feed + map по чатам пользователя."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from chat_link.models.membership import ChatMembership
from events.cursor import (
    FeedCursor,
    decode_feed_cursor,
    encode_feed_cursor,
    is_after_cursor,
)
from events.db.event import EventRow
from events.models.event import Event, EventCreate, EventSource, EventUpdate
from events.weight import (
    allowed_in_city_feed,
    allowed_on_map,
    compute_weight,
    haversine_m,
    map_icon_category,
)
from project.logging_setup import get_logger

logger = get_logger(__name__)


class EventScope(StrEnum):
    NEARBY = "nearby"
    CITY = "city"


@dataclass(slots=True)
class FeedPage:
    items: list[Event]
    next_cursor: str | None
    scope: EventScope


@dataclass(slots=True)
class MapPoint:
    id: int
    title: str
    lat: float
    lon: float
    importance: int
    category: str
    disaster_flag: bool
    body: str | None = None


def _normalize_source(source: EventSource | str) -> str:
    if isinstance(source, EventSource):
        return source.value
    value = str(source).strip()
    if not value:
        raise ValueError("source не может быть пустым")
    return value


def _validate_importance(importance: int) -> None:
    if importance not in (1, 2, 3):
        raise ValueError(f"importance должен быть 1..3, получено {importance}")


def _to_domain(row: EventRow, *, distance_m: float | None = None) -> Event:
    weight = compute_weight(
        importance=row.importance,
        source=row.source,
        distance_m=distance_m,
    )
    return Event(
        id=row.id,
        title=row.title,
        body=row.body,
        importance=row.importance,
        source=row.source,
        lat=row.lat,
        lon=row.lon,
        weight=weight,
        source_msg_id=row.source_msg_id,
        disaster_flag=row.disaster_flag,
        source_url=row.source_url,
        image_url=row.image_url,
        created_at=row.created_at,
        updated_at=row.updated_at,
        distance_m=distance_m,
    )


def create_event(session: Session, data: EventCreate) -> Event:
    """
    Создать финальное событие (только in-process: парсеры / бот / скрипты).

    KAN-19 ml_dedup: сюда же позже вставить merge до insert.
    """
    _validate_importance(data.importance)
    source = _normalize_source(data.source)
    base_weight = compute_weight(importance=data.importance, source=source, distance_m=None)

    row = EventRow(
        title=data.title.strip(),
        body=data.body.strip(),
        importance=data.importance,
        source=source,
        lat=data.lat,
        lon=data.lon,
        weight=base_weight,
        source_msg_id=data.source_msg_id,
        disaster_flag=data.disaster_flag,
        source_url=data.source_url,
        image_url=data.image_url,
    )
    session.add(row)
    session.flush()
    logger.info(
        "Событие создано id=%s importance=%s source=%s",
        row.id,
        row.importance,
        row.source,
    )
    return _to_domain(row)


def get_event(session: Session, event_id: int) -> Event | None:
    row = session.get(EventRow, event_id)
    return _to_domain(row) if row else None


def update_event(session: Session, event_id: int, data: EventUpdate) -> Event | None:
    row = session.get(EventRow, event_id)
    if row is None:
        return None

    if data.title is not None:
        row.title = data.title.strip()
    if data.body is not None:
        row.body = data.body.strip()
    if data.importance is not None:
        _validate_importance(data.importance)
        row.importance = data.importance
    if data.source is not None:
        row.source = _normalize_source(data.source)
    if data.clear_geo:
        row.lat = None
        row.lon = None
    else:
        if data.lat is not None:
            row.lat = data.lat
        if data.lon is not None:
            row.lon = data.lon
    if data.source_msg_id is not None:
        row.source_msg_id = data.source_msg_id
    if data.disaster_flag is not None:
        row.disaster_flag = data.disaster_flag
    if data.source_url is not None:
        row.source_url = data.source_url
    if data.clear_image:
        row.image_url = None
    elif data.image_url is not None:
        row.image_url = data.image_url

    row.weight = compute_weight(
        importance=row.importance,
        source=row.source,
        distance_m=None,
    )
    session.flush()
    logger.info("Событие обновлено id=%s", row.id)
    return _to_domain(row)


def delete_event(session: Session, event_id: int) -> bool:
    row = session.get(EventRow, event_id)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    logger.info("Событие удалено id=%s", event_id)
    return True


def _distance_for_scope(
    row: EventRow,
    memberships: list[ChatMembership],
    *,
    scope: EventScope,
) -> float | None:
    """Мин. расстояние до чатов пользователя, если событие попадает в радиус scope."""
    if row.lat is None or row.lon is None:
        return None
    best: float | None = None
    for membership in memberships:
        distance_m = haversine_m(membership.lat, membership.lon, row.lat, row.lon)
        radius = (
            membership.nearby_radius_m if scope is EventScope.NEARBY else membership.city_radius_m
        )
        if distance_m <= radius and (best is None or distance_m < best):
            best = distance_m
    return best


def list_feed(
    session: Session,
    *,
    scope: EventScope | str,
    memberships: list[ChatMembership],
    limit: int = 20,
    cursor: str | None = None,
) -> FeedPage:
    """
    TikTok-лента по чатам пользователя: keyset (weight DESC, id DESC).

    Гео берётся из memberships (чаты), не из query-параметров webapp.
    """
    if not memberships:
        raise ValueError("У пользователя нет чатов — лента пуста")

    scope_value = EventScope(scope)
    if limit < 1:
        raise ValueError("limit должен быть >= 1")

    parsed: FeedCursor | None = decode_feed_cursor(cursor) if cursor else None
    scored: list[Event] = []

    rows = session.scalars(
        select(EventRow).where(EventRow.lat.is_not(None), EventRow.lon.is_not(None))
    ).all()

    for row in rows:
        distance_m = _distance_for_scope(row, memberships, scope=scope_value)
        if distance_m is None:
            continue
        if scope_value is EventScope.CITY and not allowed_in_city_feed(
            importance=row.importance,
            disaster_flag=row.disaster_flag,
        ):
            continue
        event = _to_domain(row, distance_m=distance_m)
        if parsed is not None and not is_after_cursor(
            weight=event.weight,
            event_id=event.id,
            cursor=parsed,
        ):
            continue
        scored.append(event)

    scored.sort(key=lambda item: (item.weight, item.id), reverse=True)
    page = scored[:limit]
    next_cursor: str | None = None
    if len(scored) > limit:
        last = page[-1]
        next_cursor = encode_feed_cursor(FeedCursor(weight=last.weight, event_id=last.id))

    return FeedPage(items=page, next_cursor=next_cursor, scope=scope_value)


def list_map_points(
    session: Session,
    *,
    memberships: list[ChatMembership],
    limit: int = 500,
) -> list[MapPoint]:
    """
    Точки карты по чатам пользователя (city-радиус).

    Без бытовухи (importance=3) — только важное и катастрофы.
    """
    if not memberships:
        raise ValueError("У пользователя нет чатов — карта пуста")
    if limit < 1:
        raise ValueError("limit должен быть >= 1")

    points: list[MapPoint] = []
    rows = session.scalars(
        select(EventRow).where(EventRow.lat.is_not(None), EventRow.lon.is_not(None))
    ).all()

    for row in rows:
        distance_m = _distance_for_scope(row, memberships, scope=EventScope.CITY)
        if distance_m is None:
            continue
        if not allowed_on_map(importance=row.importance, disaster_flag=row.disaster_flag):
            continue
        assert row.lat is not None and row.lon is not None
        points.append(
            MapPoint(
                id=row.id,
                title=row.title,
                lat=row.lat,
                lon=row.lon,
                importance=row.importance,
                category=map_icon_category(
                    importance=row.importance,
                    disaster_flag=row.disaster_flag,
                ),
                disaster_flag=row.disaster_flag,
                body=row.body,
            )
        )

    points.sort(key=lambda p: (p.importance, p.id))
    return points[:limit]
