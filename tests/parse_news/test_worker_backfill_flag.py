"""Тесты логики backfill / лимита пачки (без сети и без полного worker)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from events.handlers.crud import create_event
from events.models.event import EventCreate, EventSource
from parse_news.handlers.state import count_events_for_outlet, get_or_create_cursor
from parse_news.handlers.worker import _backfill_done_after_collect, _need_backfill
from parse_news.models.article import RawNewsArticle
from parse_news.sources.base import CollectResult


def test_need_backfill_new_cursor(db_session) -> None:
    cursor = get_or_create_cursor(db_session, "tass")
    assert (
        _need_backfill(
            backfill_complete=cursor.backfill_complete,
            outlet_event_count=count_events_for_outlet(db_session, "tass"),
        )
        is True
    )


def test_need_backfill_complete_but_no_events(db_session) -> None:
    cursor = get_or_create_cursor(db_session, "ria")
    cursor.backfill_complete = True
    db_session.flush()
    assert (
        _need_backfill(
            backfill_complete=True,
            outlet_event_count=0,
        )
        is True
    )


def test_need_backfill_complete_with_events(db_session) -> None:
    cursor = get_or_create_cursor(db_session, "msk1")
    cursor.backfill_complete = True
    db_session.flush()

    create_event(
        db_session,
        EventCreate(
            title="Старая новость",
            body="Тело",
            importance=3,
            source=EventSource.NEWS,
            source_msg_id="msk1:76634109",
        ),
    )

    assert (
        _need_backfill(
            backfill_complete=True,
            outlet_event_count=count_events_for_outlet(db_session, "msk1"),
        )
        is False
    )


def test_bootstrap_also_backfills() -> None:
    assert (
        _need_backfill(
            backfill_complete=False,
            outlet_event_count=0,
        )
        is True
    )


def test_reopen_backfill_if_oldest_newer_than_lookback() -> None:
    since = datetime.now(UTC) - timedelta(days=7)
    oldest = datetime.now(UTC) - timedelta(days=1)
    assert (
        _need_backfill(
            backfill_complete=True,
            outlet_event_count=10,
            oldest_seen_at=oldest,
            lookback_since=since,
        )
        is True
    )


def test_production_max_batch_does_not_complete_backfill() -> None:
    articles = [
        RawNewsArticle(
            outlet="ria",
            external_id=str(i),
            url=f"https://ria.ru/{i}",
            title=f"t{i}",
            published_at=datetime(2026, 9, 17, tzinfo=UTC),
        )
        for i in range(30)
    ]
    result = CollectResult(articles=articles, next_cursor="20260910", reached_since=False)
    assert (
        _backfill_done_after_collect(
            previous_complete=False,
            mode="backfill",
            result=result,
            max_articles=30,
            outlet_event_count=30,
            soft_cap=0,
        )
        is False
    )


def test_bootstrap_soft_cap_completes() -> None:
    articles = [
        RawNewsArticle(
            outlet="msk1",
            external_id="1",
            url="https://msk1.ru/1",
            title="t",
            published_at=datetime(2026, 9, 17, tzinfo=UTC),
        )
    ]
    result = CollectResult(articles=articles, next_cursor="2", reached_since=False)
    assert (
        _backfill_done_after_collect(
            previous_complete=False,
            mode="backfill",
            result=result,
            max_articles=40,
            outlet_event_count=40,
            soft_cap=40,
        )
        is True
    )
    assert (
        _backfill_done_after_collect(
            previous_complete=False,
            mode="backfill",
            result=result,
            max_articles=40,
            outlet_event_count=1,
            soft_cap=0,
        )
        is False
    )


def test_backfill_complete_when_reached_since() -> None:
    result = CollectResult(articles=[], next_cursor=None, reached_since=True)
    assert (
        _backfill_done_after_collect(
            previous_complete=False,
            mode="backfill",
            result=result,
            max_articles=500,
            outlet_event_count=0,
            soft_cap=0,
        )
        is True
    )


def test_backfill_complete_when_short_batch_without_cursor() -> None:
    articles = [
        RawNewsArticle(
            outlet="m24",
            external_id="1",
            url="https://www.m24.ru/1",
            title="t",
            published_at=datetime(2026, 9, 17, tzinfo=UTC),
        )
    ]
    result = CollectResult(articles=articles, next_cursor=None, reached_since=False)
    assert (
        _backfill_done_after_collect(
            previous_complete=False,
            mode="backfill",
            result=result,
            max_articles=500,
            outlet_event_count=1,
            soft_cap=0,
        )
        is True
    )
