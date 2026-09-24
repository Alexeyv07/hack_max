"""Тесты persist_article (без сети)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from address.db.address import AddressRow
from address.resolve import GeoBind, GeoByLevel
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


def _moscow_address(db_session) -> AddressRow:
    row = AddressRow(
        postal_code="125009",
        address_text="Москва, город",
        city="Москва",
        latitude=Decimal("55.7558000"),
        longitude=Decimal("37.6173000"),
        is_private=False,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_persist_article_skips_without_geo(db_session) -> None:
    article = _sample_article()
    assert persist_article(db_session, article, address_id=None) is None


def test_persist_article_idempotent_and_source_msg_id(db_session) -> None:
    article = _sample_article()
    addr = _moscow_address(db_session)
    geo = GeoBind(address_id=addr.id, geo_by=GeoByLevel.CITY)

    first = persist_article(db_session, article, geo=geo)
    assert first is not None
    assert first.source == EventSource.NEWS.value
    assert first.source_msg_id == "tass:1234567"
    assert first.address_id == addr.id

    second = persist_article(db_session, article, geo=geo)
    assert second is None
