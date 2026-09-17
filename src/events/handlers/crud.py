"""CRUD (in-process) и выборки для webapp: feed + map по чатам пользователя."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from itertools import batched

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from address.db.address import AddressRow
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


def _get_address(session: Session, address_id: int | None) -> AddressRow | None:
    if address_id is None:
        return None
    address = session.get(AddressRow, address_id)
    if address is None:
        raise ValueError(f"Адрес id={address_id} не найден")
    return address


def _outlet_reliability_map() -> dict[str, float]:
    try:
        from project.config import get_settings

        return {key: src.reliability for key, src in get_settings().news_parser.sources.items()}
    except Exception:
        return {}


def _to_domain(
    row: EventRow,
    *,
    distance_m: float | None = None,
    now: datetime | None = None,
) -> Event:
    weight = compute_weight(
        importance=row.importance,
        source=row.source,
        distance_m=distance_m,
        geo_by=row.geo_by,
        published_at=row.published_at,
        created_at=row.created_at,
        source_msg_id=row.source_msg_id,
        outlet_reliability=_outlet_reliability_map(),
        now=now,
    )
    address = row.address
    return Event(
        id=row.id,
        title=row.title,
        body=row.body,
        importance=row.importance,
        source=row.source,
        address_id=row.address_id,
        lat=float(address.latitude) if address is not None else None,
        lon=float(address.longitude) if address is not None else None,
        weight=weight,
        source_msg_id=row.source_msg_id,
        disaster_flag=row.disaster_flag,
        source_url=row.source_url,
        image_url=row.image_url,
        geo_by=row.geo_by,
        published_at=row.published_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        distance_m=distance_m,
    )


def list_existing_source_msg_ids(
    session: Session,
    *,
    source: EventSource | str,
    source_msg_ids: Iterable[str],
) -> set[str]:
    normalized = _normalize_source(source)
    unique_ids = list(dict.fromkeys(source_msg_ids))
    if not unique_ids:
        return set()
    found: set[str] = set()
    for batch in batched(unique_ids, 1000):
        rows = session.scalars(
            select(EventRow.source_msg_id).where(
                EventRow.source == normalized,
                EventRow.source_msg_id.in_(batch),
            )
        ).all()
        found.update(row for row in rows if row is not None)
    return found


def create_event(session: Session, data: EventCreate) -> Event:
    """
    Создать финальное событие (только in-process: воркеры парсеров / бот / скрипты).

    Типичный вход с парсера::

        from parser_common import persist_candidate
        # или: create_event(session, to_event_create(normalize(candidate)))

    Геопозиция хранится ссылкой на Address, а не копией latitude/longitude.
    KAN-19 ml_dedup: сюда же позже вставить merge до insert.
    """
    _validate_importance(data.importance)
    source = _normalize_source(data.source)
    base_weight = compute_weight(
        importance=data.importance,
        source=source,
        distance_m=None,
        geo_by=data.geo_by,
        published_at=data.published_at,
        source_msg_id=data.source_msg_id,
        outlet_reliability=_outlet_reliability_map(),
    )

    row = EventRow(
        title=data.title.strip(),
        body=data.body.strip(),
        importance=data.importance,
        source=source,
        address=_get_address(session, data.address_id),
        geo_by=data.geo_by,
        weight=base_weight,
        source_msg_id=data.source_msg_id,
        disaster_flag=data.disaster_flag,
        source_url=data.source_url,
        image_url=data.image_url,
        published_at=data.published_at,
    )
    session.add(row)
    session.flush()
    logger.debug(
        "Событие создано id=%s importance=%s source=%s address_id=%s",
        row.id,
        row.importance,
        row.source,
        row.address_id,
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
    if data.clear_address:
        row.address = None
        row.geo_by = None
    elif data.address_id is not None:
        row.address = _get_address(session, data.address_id)
        if data.geo_by is not None:
            row.geo_by = data.geo_by
    elif data.geo_by is not None:
        row.geo_by = data.geo_by
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
    if data.published_at is not None:
        row.published_at = data.published_at

    row.weight = compute_weight(
        importance=row.importance,
        source=row.source,
        distance_m=None,
        geo_by=row.geo_by,
        published_at=row.published_at,
        created_at=row.created_at,
        source_msg_id=row.source_msg_id,
        outlet_reliability=_outlet_reliability_map(),
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
    if row.address is None:
        return None
    lat, lon = float(row.address.latitude), float(row.address.longitude)
    best: float | None = None
    for membership in memberships:
        distance_m = haversine_m(membership.lat, membership.lon, lat, lon)
        radius = (
            membership.nearby_radius_m if scope is EventScope.NEARBY else membership.city_radius_m
        )
        if distance_m <= radius and (best is None or distance_m < best):
            best = distance_m
    return best


def _event_rows_with_address(session: Session) -> list[EventRow]:
    return list(
        session.scalars(
            select(EventRow)
            .options(joinedload(EventRow.address))
            .where(EventRow.address_id.is_not(None))
        ).all()
    )


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

    Гео чатов берётся из memberships; гео события — из связанного Address.
    """
    if not memberships:
        raise ValueError("У пользователя нет чатов — лента пуста")

    scope_value = EventScope(scope)
    if limit < 1:
        raise ValueError("limit должен быть >= 1")

    parsed: FeedCursor | None = decode_feed_cursor(cursor) if cursor else None
    scored: list[Event] = []
    now = datetime.now(UTC)

    for row in _event_rows_with_address(session):
        distance_m = _distance_for_scope(row, memberships, scope=scope_value)
        if distance_m is None:
            continue
        if scope_value is EventScope.CITY and not allowed_in_city_feed(
            importance=row.importance,
            disaster_flag=row.disaster_flag,
        ):
            continue
        event = _to_domain(row, distance_m=distance_m, now=now)
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
    for row in _event_rows_with_address(session):
        distance_m = _distance_for_scope(row, memberships, scope=EventScope.CITY)
        if distance_m is None:
            continue
        if not allowed_on_map(importance=row.importance, disaster_flag=row.disaster_flag):
            continue
        assert row.address is not None
        points.append(
            MapPoint(
                id=row.id,
                title=row.title,
                lat=float(row.address.latitude),
                lon=float(row.address.longitude),
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
