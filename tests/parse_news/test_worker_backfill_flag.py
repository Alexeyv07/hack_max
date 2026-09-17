"""Тесты логики backfill / лимита пачки (без сети и без полного worker)."""

from __future__ import annotations

from datetime import UTC, datetime

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


def test_max_articles_is_per_source_batch_not_global_stop() -> None:
    """Лимит — размер одной пачки collect(), не суммарный стоп по всем СМИ."""
    articles = [
        RawNewsArticle(
            outlet="ria",
            external_id=str(i),
            url=f"https://ria.ru/{i}",
            title=f"t{i}",
            published_at=datetime(2026, 9, 17, tzinfo=UTC),
        )
        for i in range(500)
    ]
    result = CollectResult(articles=articles, next_cursor="20260910", reached_since=False)
    # Набрали ровно max — backfill НЕ завершён.
    assert (
        _backfill_done_after_collect(
            previous_complete=False,
            mode="backfill",
            result=result,
            max_articles=500,
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
        )
        is True
    )
