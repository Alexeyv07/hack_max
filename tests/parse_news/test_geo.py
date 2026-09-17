"""Тесты геопривязки новостей."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from address.db.address import AddressRow
from parse_news.handlers.geo import (
    MoscowStreetIndex,
    extract_street_hints,
    resolve_article_geo,
)
from parse_news.models.article import RawNewsArticle


def _add_street_addresses(db_session, street: str) -> None:
    for house, lat in (("1", "55.757"), ("7", "55.758")):
        db_session.add(
            AddressRow(
                postal_code="125009",
                address_text=f"\u041c\u043e\u0441\u043a\u0432\u0430, \u0443\u043b\u0438\u0446\u0430 {street}, \u0434. {house}",
                city="\u041c\u043e\u0441\u043a\u0432\u0430",
                street=f"\u0443\u043b\u0438\u0446\u0430 {street}",
                house=house,
                latitude=Decimal(lat),
                longitude=Decimal("37.615"),
                is_private=False,
            )
        )
    db_session.flush()


def test_resolve_article_geo_without_place_federal(db_session) -> None:
    article = RawNewsArticle(
        outlet="ria",
        external_id="2118199709",
        url="https://ria.ru/20260917/foo-2118199709.html",
        title="Event without place",
        published_at=datetime(2026, 9, 17, 12, 0, tzinfo=UTC),
        body="No street and no postcode here.",
    )
    assert resolve_article_geo(db_session, article) is None


def test_resolve_article_geo_outlet_default_city(db_session) -> None:
    article = RawNewsArticle(
        outlet="m24",
        external_id="1",
        url="https://www.m24.ru/news/x",
        title="Local news without street",
        published_at=datetime(2026, 9, 17, tzinfo=UTC),
        body="Something happened today.",
    )
    bind = resolve_article_geo(db_session, article)
    assert bind is not None
    assert bind.geo_by == "city"
    row = db_session.get(AddressRow, bind.address_id)
    assert row is not None
    assert row.city == "\u041c\u043e\u0441\u043a\u0432\u0430"
    assert row.street is None


def test_extract_street_hints() -> None:
    text = (
        "\u0410\u0432\u0430\u0440\u0438\u044f \u043d\u0430 \u0443\u043b\u0438\u0446\u0435 "
        "\u0422\u0432\u0435\u0440\u0441\u043a\u0430\u044f \u043f\u0435\u0440\u0435\u043a\u0440\u044b\u043b\u0430"
    )
    hints = extract_street_hints(text)
    needle = "\u0442\u0432\u0435\u0440\u0441\u043a\u0430\u044f"
    assert any(needle in h.lower() for h in hints), hints


def test_resolve_article_geo_by_street_and_house(db_session) -> None:
    street = "\u0422\u0432\u0435\u0440\u0441\u043a\u0430\u044f"
    _add_street_addresses(db_session, street)
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
    bind = resolve_article_geo(db_session, article, street_index=index)
    assert bind is not None
    assert bind.geo_by == "home"
    row = db_session.get(AddressRow, bind.address_id)
    assert row is not None
    assert row.house == "7"


def test_resolve_article_geo_by_street_only(db_session) -> None:
    street = "\u0410\u0440\u0431\u0430\u0442"
    _add_street_addresses(db_session, street)
    article = RawNewsArticle(
        outlet="mskagency",
        external_id="2",
        url="https://mskagency.ru/x",
        title=f"\u0421\u043e\u0431\u044b\u0442\u0438\u0435 \u043d\u0430 \u0443\u043b\u0438\u0446\u0435 {street}",
        published_at=datetime(2026, 9, 17, tzinfo=UTC),
        body="ok",
    )
    bind = resolve_article_geo(db_session, article)
    assert bind is not None
    assert bind.geo_by == "street"


def test_resolve_article_geo_from_source_fields(db_session) -> None:
    street = "\u0422\u0432\u0435\u0440\u0441\u043a\u0430\u044f"
    _add_street_addresses(db_session, street)
    article = RawNewsArticle(
        outlet="ria",
        external_id="9",
        url="https://ria.ru/x",
        title="No place in title",
        published_at=datetime(2026, 9, 17, tzinfo=UTC),
        body="plain",
        geo_city="\u041c\u043e\u0441\u043a\u0432\u0430",
        geo_street=f"\u0443\u043b\u0438\u0446\u0430 {street}",
        geo_house="1",
    )
    bind = resolve_article_geo(db_session, article)
    assert bind is not None
    assert bind.geo_by == "home"
