"""Тесты persist_article (без сети)."""

from __future__ import annotations

from datetime import UTC, datetime

from events.models.event import EventSource
from parse_news.handlers.ingest import persist_article
from parse_news.models.article import RawNewsArticle


def _sample_article(*, external_id: str = "1234567") -> RawNewsArticle:
    return RawNewsArticle(
        outlet="tass",
        external_id=external_id,
        url=f"https://tass.ru/obschestvo/{external_id}",
        title="Тестовая новость",
        published_at=datetime(2026, 9, 17, 10, 0, tzinfo=UTC),
        body="Текст без индекса.",
    )


def test_persist_article_idempotent_and_source_msg_id(db_session) -> None:
    article = _sample_article()

    first = persist_article(db_session, article, address_id=None)
    assert first is not None
    assert first.source == EventSource.NEWS.value
    assert first.source_msg_id == "tass:1234567"
    assert first.address_id is None

    second = persist_article(db_session, article, address_id=None)
    assert second is None
