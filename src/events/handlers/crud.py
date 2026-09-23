"""CRUD (in-process) и выборки для webapp: feed + map."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from itertools import batched

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from address.db.address import AddressRow
from events.cursor import (
    FeedCursor,
    decode_feed_cursor,
    encode_feed_cursor,
    is_after_cursor,
)
from events.db.event import EventRow
from events.models.event import Event, EventCreate, EventSource, EventUpdate
from events.weight import (
    allowed_on_map,
    apply_nearby_boosts,
    bbox_delta_degrees,
    compute_weight,
    event_is_active_now,
    haversine_m,
    map_icon_category,
    proximity_band,
    streets_match,
)
from project.config import get_settings
from project.logging_setup import get_logger
from user_chat.handlers.membership import list_memberships_for_user
from user_chat.models.membership import ChatMembership

logger = get_logger(__name__)

# Верхняя граница кандидатов для персональной nearby (bbox → haversine в Python).
_NEARBY_CANDIDATE_CAP = 2_000


class EventScope(StrEnum):
    NEARBY = "nearby"
    CITY = "city"


@dataclass(frozen=True, slots=True)
class FeedOrigin:
    """Точка «дома» пользователя для nearby (первая улица чата + радиус)."""

    lat: float
    lon: float
    radius_m: float
    chat_count: int


@dataclass(slots=True)
class FeedPage:
    items: list[Event]
    next_cursor: str | None
    scope: EventScope
    origin: FeedOrigin | None = None


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

        settings = get_settings()
        out = {key: src.reliability for key, src in settings.news_parser.sources.items()}
        out.update({key: src.reliability for key, src in settings.mc_parser.sources.items()})
        return out
    except Exception:
        return {}


def _to_domain(
    row: EventRow,
    *,
    distance_m: float | None = None,
    now: datetime | None = None,
    weight_override: float | None = None,
    proximity: str | None = None,
    same_street: bool = False,
    is_active_now: bool | None = None,
) -> Event:
    weight = (
        weight_override
        if weight_override is not None
        else compute_weight(
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
        location=address.address_text if address is not None else None,
        published_at=row.published_at,
        active_from=row.active_from,
        active_to=row.active_to,
        created_at=row.created_at,
        updated_at=row.updated_at,
        distance_m=distance_m,
        proximity=proximity,
        same_street=same_street,
        is_active_now=is_active_now,
    )


def _min_distance_m(
    *,
    event_lat: float,
    event_lon: float,
    origins: Sequence[ChatMembership],
) -> float:
    return min(haversine_m(o.lat, o.lon, event_lat, event_lon) for o in origins)


def _same_street_for_origins(
    event_street: str | None,
    origins: Sequence[ChatMembership],
) -> bool:
    return any(streets_match(event_street, origin.street) for origin in origins)


def _bbox_predicate(origins: Sequence[ChatMembership], radius_m: float):
    """OR по bbox вокруг каждой улицы чата (грубый prefilter до haversine)."""
    clauses = []
    for origin in origins:
        d_lat, d_lon = bbox_delta_degrees(lat=origin.lat, radius_m=radius_m)
        clauses.append(
            and_(
                AddressRow.latitude.between(origin.lat - d_lat, origin.lat + d_lat),
                AddressRow.longitude.between(origin.lon - d_lon, origin.lon + d_lon),
            )
        )
    return or_(*clauses)


def _feed_origin(memberships: Sequence[ChatMembership], radius_m: float) -> FeedOrigin:
    first = memberships[0]
    return FeedOrigin(
        lat=first.lat,
        lon=first.lon,
        radius_m=radius_m,
        chat_count=len(memberships),
    )


def _list_nearby_feed(
    session: Session,
    *,
    memberships: Sequence[ChatMembership],
    limit: int,
    cursor: str | None,
    now: datetime,
) -> FeedPage:
    settings = get_settings()
    radius_m = float(settings.events.nearby_radius_m)
    origin = _feed_origin(memberships, radius_m)
    stmt = (
        _addressed_event_stmt()
        .where(
            EventRow.importance.in_((1, 2)),
            EventRow.geo_by.in_(("street", "home")),
            _not_expired_clause(now),
            _bbox_predicate(memberships, radius_m),
        )
        .limit(_NEARBY_CANDIDATE_CAP)
    )
    rows = list(session.scalars(stmt).unique().all())
    scored: list[Event] = []
    for row in rows:
        assert row.address is not None
        event_lat = float(row.address.latitude)
        event_lon = float(row.address.longitude)
        distance = _min_distance_m(
            event_lat=event_lat,
            event_lon=event_lon,
            origins=memberships,
        )
        if distance > radius_m:
            continue
        same_street = _same_street_for_origins(row.address.street, memberships)
        active = event_is_active_now(
            active_from=row.active_from,
            active_to=row.active_to,
            now=now,
        )
        base = compute_weight(
            importance=row.importance,
            source=row.source,
            distance_m=distance,
            geo_by=row.geo_by,
            published_at=row.published_at,
            created_at=row.created_at,
            source_msg_id=row.source_msg_id,
            outlet_reliability=_outlet_reliability_map(),
            now=now,
            distance_scale_m=radius_m,
        )
        rank = apply_nearby_boosts(
            base,
            same_street=same_street,
            is_active_now=active,
        )
        scored.append(
            _to_domain(
                row,
                distance_m=distance,
                now=now,
                weight_override=rank,
                proximity=proximity_band(distance),
                same_street=same_street,
                is_active_now=active,
            )
        )

    scored.sort(key=lambda item: (item.weight, item.id), reverse=True)
    parsed: FeedCursor | None = decode_feed_cursor(cursor) if cursor else None
    if parsed is not None:
        scored = [
            item
            for item in scored
            if is_after_cursor(weight=item.weight, event_id=item.id, cursor=parsed)
        ]

    page_items = scored[:limit]
    next_cursor: str | None = None
    if len(scored) > limit:
        last = page_items[-1]
        next_cursor = encode_feed_cursor(FeedCursor(weight=last.weight, event_id=last.id))

    return FeedPage(
        items=page_items,
        next_cursor=next_cursor,
        scope=EventScope.NEARBY,
        origin=origin,
    )


def _list_city_feed(
    session: Session,
    *,
    limit: int,
    cursor: str | None,
    now: datetime,
) -> FeedPage:
    """Городская лента: все события с Address.city = Москва (любой geo_by)."""
    stmt = (
        _addressed_event_stmt()
        .where(
            EventRow.importance.in_((1, 2)),
            _moscow_city_clause(),
            _not_expired_clause(now),
        )
        .limit(_NEARBY_CANDIDATE_CAP)
    )
    rows = list(session.scalars(stmt).unique().all())
    scored: list[Event] = []
    for row in rows:
        active = event_is_active_now(
            active_from=row.active_from,
            active_to=row.active_to,
            now=now,
        )
        base = compute_weight(
            importance=row.importance,
            source=row.source,
            distance_m=None,
            geo_by=row.geo_by,
            published_at=row.published_at,
            created_at=row.created_at,
            source_msg_id=row.source_msg_id,
            outlet_reliability=_outlet_reliability_map(),
            now=now,
        )
        rank = apply_nearby_boosts(base, same_street=False, is_active_now=active)
        scored.append(
            _to_domain(
                row,
                distance_m=None,
                now=now,
                weight_override=rank,
                is_active_now=active,
            )
        )

    scored.sort(key=lambda item: (item.weight, item.id), reverse=True)
    parsed: FeedCursor | None = decode_feed_cursor(cursor) if cursor else None
    if parsed is not None:
        scored = [
            item
            for item in scored
            if is_after_cursor(weight=item.weight, event_id=item.id, cursor=parsed)
        ]

    page_items = scored[:limit]
    next_cursor: str | None = None
    if len(scored) > limit:
        last = page_items[-1]
        next_cursor = encode_feed_cursor(FeedCursor(weight=last.weight, event_id=last.id))

    return FeedPage(items=page_items, next_cursor=next_cursor, scope=EventScope.CITY)


def _not_expired_clause(now: datetime):
    """Скрыть события с известным active_to в прошлом (ml_time)."""
    return or_(EventRow.active_to.is_(None), EventRow.active_to >= now)


def _moscow_city_clause():
    # Точное совпадение: SQLite lower() не трогает кириллицу.
    return AddressRow.city == "Москва"


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


def _normalize_optional_title(title: str | None) -> str | None:
    if title is None:
        return None
    cleaned = title.strip()
    return cleaned or None


def _normalize_body(body: str | None) -> str:
    return body.strip() if body else ""


def create_event(session: Session, data: EventCreate) -> Event:
    """
    Создать финальное событие (только in-process: воркеры парсеров / бот / скрипты).

    Типичный вход с парсера::

        from parser_common import persist_candidate
        # или: create_event(session, to_event_create(normalize(candidate)))

    Геопозиция хранится ссылкой на Address, а не копией latitude/longitude.
    Дедуп/merge (KAN-19) — в ``persist_candidate`` / ``ml_dedup.resolve`` до вызова.
    Title необязателен: достаточно непустого body.
    """
    _validate_importance(data.importance)
    source = _normalize_source(data.source)
    title = _normalize_optional_title(data.title)
    body = _normalize_body(data.body)
    if not title and not body:
        raise ValueError("Нужен title или body")

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
        title=title,
        body=body,
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
        active_from=data.active_from,
        active_to=data.active_to,
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
        row.title = _normalize_optional_title(data.title)
    if data.body is not None:
        row.body = _normalize_body(data.body)
    if not (row.title or row.body):
        raise ValueError("Нужен title или body")
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
    if data.clear_active_from:
        row.active_from = None
    elif data.active_from is not None:
        row.active_from = data.active_from
    if data.clear_active_to:
        row.active_to = None
    elif data.active_to is not None:
        row.active_to = data.active_to

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


def _addressed_event_stmt():
    """События с непустым адресом (JOIN, без полной выгрузки таблицы)."""
    return (
        select(EventRow)
        .options(joinedload(EventRow.address))
        .join(AddressRow, EventRow.address_id == AddressRow.id)
        .where(func.length(func.trim(AddressRow.address_text)) > 0)
    )


def list_feed(
    session: Session,
    *,
    scope: EventScope | str,
    limit: int = 20,
    cursor: str | None = None,
    max_user_id: int | None = None,
) -> FeedPage:
    """
    TikTok-лента nearby|city.

    Общее:
    - только события с address_id + непустым Address.address_text;
    - importance 1|2 (3 не показываем);
    - keyset cursor по weight DESC, id DESC.

    Nearby (персонально по улице чата):
    - нужны memberships пользователя; иначе пустая страница;
    - geo_by street|home;
    - отсев дальше ``events.nearby_radius_m`` (~6 км);
    - вес с distance_m + same_street / ml_time (просроченные active_to скрыты).

    City: все события с Address.city=Москва; ml_time как у nearby.
    """
    scope_value = EventScope(scope)
    if limit < 1:
        raise ValueError("limit должен быть >= 1")

    now = datetime.now(UTC)
    if scope_value is EventScope.CITY:
        return _list_city_feed(session, limit=limit, cursor=cursor, now=now)

    if max_user_id is None:
        return FeedPage(items=[], next_cursor=None, scope=EventScope.NEARBY, origin=None)

    memberships = list_memberships_for_user(session, max_user_id)
    if not memberships:
        # Без привязанного чата «рядом» нечего ранжировать — городская лента отдельно.
        return FeedPage(items=[], next_cursor=None, scope=EventScope.NEARBY, origin=None)

    return _list_nearby_feed(
        session,
        memberships=memberships,
        limit=limit,
        cursor=cursor,
        now=now,
    )


def list_map_points(
    session: Session,
    *,
    limit: int = 500,
) -> list[MapPoint]:
    """
    Точки карты: все события с адресом.

    Без бытовухи (importance=3) — только важное и катастрофы.
    """
    if limit < 1:
        raise ValueError("limit должен быть >= 1")

    stmt = (
        _addressed_event_stmt()
        .where(EventRow.importance.in_((1, 2)))
        .order_by(EventRow.importance.asc(), EventRow.id.asc())
        .limit(limit)
    )
    points: list[MapPoint] = []
    for row in session.scalars(stmt).unique().all():
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

    return points
