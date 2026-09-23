"""CRUD (in-process) и выборки для webapp: feed + map."""

from __future__ import annotations

from collections.abc import Iterable
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
)
from events.db.event import EventRow
from events.models.event import Event, EventCreate, EventSource, EventUpdate
from events.weight import (
    allowed_on_map,
    compute_weight,
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
        location=address.address_text if address is not None else None,
        published_at=row.published_at,
        active_from=row.active_from,
        active_to=row.active_to,
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
    Дедуп/merge (KAN-19) — в ``persist_candidate`` / ``ml_dedup.resolve`` до вызова.
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
) -> FeedPage:
    """
    TikTok-лента: одна выдача всем, keyset (weight DESC, id DESC).

    Правила:
    - только события с address_id + непустым Address.address_text;
    - importance 1|2 (3 не показываем ни в одной ленте);
    - nearby → geo_by street|home; city → geo_by city;
    - порядок по weight (затем id).
    """
    scope_value = EventScope(scope)
    if limit < 1:
        raise ValueError("limit должен быть >= 1")

    geo_values = ("street", "home") if scope_value is EventScope.NEARBY else ("city",)
    stmt = (
        _addressed_event_stmt()
        .where(
            EventRow.importance.in_((1, 2)),
            EventRow.geo_by.in_(geo_values),
        )
        .order_by(EventRow.weight.desc(), EventRow.id.desc())
    )

    parsed: FeedCursor | None = decode_feed_cursor(cursor) if cursor else None
    if parsed is not None:
        # Keyset: строго после (weight, id) в порядке DESC.
        stmt = stmt.where(
            or_(
                EventRow.weight < parsed.weight,
                and_(EventRow.weight == parsed.weight, EventRow.id < parsed.event_id),
            )
        )

    rows = list(session.scalars(stmt.limit(limit + 1)).unique().all())
    now = datetime.now(UTC)
    page_rows = rows[:limit]
    items: list[Event] = []
    for row in page_rows:
        event = _to_domain(row, distance_m=None, now=now)
        # Курсор и ORDER BY по persisted weight — иначе page2 дублирует page1.
        event.weight = float(row.weight)
        items.append(event)
    next_cursor: str | None = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = encode_feed_cursor(FeedCursor(weight=last.weight, event_id=last.id))

    return FeedPage(items=items, next_cursor=next_cursor, scope=scope_value)


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
