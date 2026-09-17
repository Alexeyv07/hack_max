"""Тесты геопривязки новостей."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from address.db.address import AddressRow
from parse_news.handlers.geo import (
    MoscowStreetIndex,
    extract_street_hints,
    resolve_article_address,
)
from parse_news.models.article import RawNewsArticle


def test_resolve_article_address_without_place(db_session) -> None:
    article = RawNewsArticle(
        outlet="ria",
        external_id="2118199709",
        url="https://ria.ru/20260917/foo-2118199709.html",
        title="Event without place",
        published_at=datetime(2026, 9, 17, 12, 0, tzinfo=UTC),
        body="No street and no postcode here.",
    )
    assert resolve_article_address(db_session, article) is None


def test_extract_street_hints() -> None:
    text = (
        "\u0410\u0432\u0430\u0440\u0438\u044f \u043d\u0430 \u0443\u043b\u0438\u0446\u0435 "
        "\u0422\u0432\u0435\u0440\u0441\u043a\u0430\u044f \u043f\u0435\u0440\u0435\u043a\u0440\u044b\u043b\u0430"
    )
    hints = extract_street_hints(text)
    needle = "\u0442\u0432\u0435\u0440\u0441\u043a\u0430\u044f"
    assert any(needle in h.lower() for h in hints), hints


def test_resolve_article_address_by_street(db_session) -> None:
    street = "\u0422\u0432\u0435\u0440\u0441\u043a\u0430\u044f"
    db_session.add(
        AddressRow(
            postal_code="125009",
            address_text=f"\u041c\u043e\u0441\u043a\u0432\u0430, \u0443\u043b\u0438\u0446\u0430 {street}, \u0434. 1",
            latitude=Decimal("55.757"),
            longitude=Decimal("37.615"),
            is_private=False,
        )
    )
    db_session.add(
        AddressRow(
            postal_code="125009",
            address_text=f"\u041c\u043e\u0441\u043a\u0432\u0430, \u0443\u043b\u0438\u0446\u0430 {street}, \u0434. 7",
            latitude=Decimal("55.758"),
            longitude=Decimal("37.616"),
            is_private=False,
        )
    )
    db_session.flush()

    index = MoscowStreetIndex.load(db_session)
    article = RawNewsArticle(
        outlet="msk1",
        external_id="1",
        url="https://msk1.ru/text/x",
        title=(
            f"\u041f\u0440\u043e\u0440\u044b\u0432 \u043d\u0430 \u0443\u043b\u0438\u0446\u0435 {street}, "
            f"\u0434\u043e\u043c 7"
        ),
        published_at=datetime(2026, 9, 17, tzinfo=UTC),
        body="ok",
    )
    address_id = resolve_article_address(db_session, article, street_index=index)
    assert address_id is not None
