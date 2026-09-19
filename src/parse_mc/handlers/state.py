"""Состояние курсора парсера УК."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from events.db.event import EventRow
from events.models.event import EventSource
from parse_mc.db.cursor import McParserCursorRow


def get_or_create_cursor(session: Session, source_key: str) -> McParserCursorRow:
    row = session.get(McParserCursorRow, source_key)
    if row is not None:
        return row
    row = McParserCursorRow(source_key=source_key, backfill_complete=False)
    session.add(row)
    session.flush()
    return row


def update_cursor(
    session: Session,
    cursor: McParserCursorRow,
    *,
    backfill_complete: bool | None = None,
    listing_cursor: str | None = None,
    oldest_seen_at: datetime | None = None,
    newest_seen_at: datetime | None = None,
    last_run_at: datetime | None = None,
    last_error: str | None = None,
    clear_error: bool = False,
) -> None:
    if backfill_complete is not None:
        cursor.backfill_complete = backfill_complete
    if listing_cursor is not None:
        cursor.listing_cursor = listing_cursor
    if oldest_seen_at is not None and (
        cursor.oldest_seen_at is None or oldest_seen_at < cursor.oldest_seen_at
    ):
        cursor.oldest_seen_at = oldest_seen_at
    if newest_seen_at is not None and (
        cursor.newest_seen_at is None or newest_seen_at > cursor.newest_seen_at
    ):
        cursor.newest_seen_at = newest_seen_at
    if last_run_at is not None:
        cursor.last_run_at = last_run_at
    if clear_error:
        cursor.last_error = None
    elif last_error is not None:
        cursor.last_error = last_error
    session.flush()


def count_events_for_outlet(session: Session, outlet: str) -> int:
    prefix = f"{outlet}:"
    count = session.scalar(
        select(func.count())
        .select_from(EventRow)
        .where(
            EventRow.source == EventSource.MC.value,
            EventRow.source_msg_id.is_not(None),
            EventRow.source_msg_id.like(f"{prefix}%"),
        )
    )
    return int(count or 0)
