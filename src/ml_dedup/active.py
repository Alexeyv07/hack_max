"""Выборка «активных» событий для окна дедупа."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from events.db.event import EventRow
from ml_dedup.models import ActiveEventView


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def is_event_active(
    *,
    now: datetime,
    active_days: int,
    published_at: datetime | None,
    created_at: datetime | None,
    active_from: datetime | None,
    active_to: datetime | None,
) -> bool:
    """
    Событие ещё в пуле дедупа/апдейта:
    - если active_to задан и уже прошёл — неактивно;
    - иначе якорь (published_at|created_at|active_from) не старше active_days.
    """
    now_a = _as_aware(now) or datetime.now(UTC)
    to = _as_aware(active_to)
    if to is not None and to < now_a:
        return False

    cutoff = now_a - timedelta(days=active_days)
    for raw in (published_at, created_at, active_from):
        anchor = _as_aware(raw)
        if anchor is not None and anchor >= cutoff:
            return True
    # нет дат — считаем активным (редкий кейс seed)
    return published_at is None and created_at is None and active_from is None


def list_active_events(
    session: Session,
    *,
    active_days: int = 21,
    now: datetime | None = None,
    limit: int = 2000,
) -> list[ActiveEventView]:
    now_a = _as_aware(now) or datetime.now(UTC)
    cutoff = now_a - timedelta(days=active_days)

    # Грубый SQL-фильтр + точная проверка is_event_active
    rows = list(
        session.scalars(
            select(EventRow)
            .options(joinedload(EventRow.address))
            .where(
                or_(
                    EventRow.active_to.is_(None),
                    EventRow.active_to >= now_a,
                ),
                or_(
                    EventRow.published_at.is_(None),
                    EventRow.published_at >= cutoff,
                    EventRow.created_at >= cutoff,
                    EventRow.active_from.is_(None),
                    EventRow.active_from >= cutoff,
                ),
            )
            .order_by(EventRow.id.desc())
            .limit(limit)
        )
        .unique()
        .all()
    )

    out: list[ActiveEventView] = []
    for row in rows:
        if not is_event_active(
            now=now_a,
            active_days=active_days,
            published_at=row.published_at,
            created_at=row.created_at,
            active_from=row.active_from,
            active_to=row.active_to,
        ):
            continue
        address = row.address
        out.append(
            ActiveEventView(
                id=row.id,
                title=row.title,
                body=row.body,
                importance=row.importance,
                disaster_flag=row.disaster_flag,
                address_id=row.address_id,
                geo_by=row.geo_by,
                source=row.source,
                source_msg_id=row.source_msg_id,
                source_url=row.source_url,
                image_url=row.image_url,
                published_at=row.published_at,
                active_from=row.active_from,
                active_to=row.active_to,
                created_at=row.created_at,
                lat=float(address.latitude) if address is not None else None,
                lon=float(address.longitude) if address is not None else None,
            )
        )
    return out
