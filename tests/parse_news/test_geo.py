"""Тесты геопривязки новостей и StreetCatalog."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from address.db.address import AddressRow
from address.street_catalog import StreetCatalog, stem_token
from parse_news.handlers.geo import extract_street_hints, resolve_article_geo
from parse_news.models.article import RawNewsArticle


def _add_row(
    db_session,
    *,
    street: str,
    house: str,
    lat: str = "55.757",
    address_text: str | None = None,
) -> AddressRow:
    row = AddressRow(
        postal_code="125009",
        address_text=address_text
        or f"\u041c\u043e\u0441\u043a\u0432\u0430, {street}, \u0434. {house}",
        city="\u041c\u043e\u0441\u043a\u0432\u0430",
        street=street,
        house=house,
        latitude=Decimal(lat),
        longitude=Decimal("37.615"),
        is_private=False,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_stem_token_adjective_cases() -> None:
    assert stem_token("тверской") == stem_token("тверская")
    assert stem_token("автозаводском") == stem_token("автозаводский")


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


def test_resolve_rejects_foreign_geo_even_local_outlet(db_session) -> None:
    article = RawNewsArticle(
        outlet="tass",
        external_id="1",
        url="https://tass.ru/1",
        title=(
            "\u041f\u0430\u043c\u0444\u0438\u043b\u043e\u0432\u0430 \u0441\u043e\u043e\u0431\u0449\u0438\u043b\u0430 "
            "\u043e \u0440\u0430\u0441\u043f\u0440\u043e\u0441\u0442\u0440\u0430\u043d\u0435\u043d\u0438\u0438 "
            "\u0443\u043a\u0440\u0430\u0438\u043d\u0441\u043a\u0438\u0445 \u043b\u0438\u0441\u0442\u043e\u0432\u043e\u043a "
            "\u0432 \u0414\u043e\u043d\u0431\u0430\u0441\u0441\u0435 \u0438 \u041d\u043e\u0432\u043e\u0440\u043e\u0441\u0441\u0438\u0438"
        ),
        published_at=datetime(2026, 9, 17, tzinfo=UTC),
        body="tass.ru",
    )
    assert resolve_article_geo(db_session, article) is None


def test_reject_dnepropetrovsk_ria_miscast(db_session) -> None:
    """Украина/Днепропетровск не должны получать московский address_id."""
    from parse_news.handlers.geo import should_skip_foreign_article

    # Улица в справочнике, на которую раньше мог «прилипнуть» топоним.
    _add_row(
        db_session,
        street="\u0443\u043b\u0438\u0446\u0430 \u0414\u043d\u0435\u043f\u0440\u043e\u043f\u0435\u0442\u0440\u043e\u0432\u0441\u043a\u0430\u044f",
        house="1",
    )
    catalog = StreetCatalog.load(db_session)

    ria = RawNewsArticle(
        outlet="ria",
        external_id="2118337723",
        url="https://ria.ru/20260917/ukraina-2118337723.html",
        title=(
            "\u0423\u043a\u0440\u0430\u0438\u043d\u0441\u043a\u0438\u0435 \u0421\u041c\u0418 "
            "\u0441\u043e\u043e\u0431\u0449\u0438\u043b\u0438 \u043e \u0432\u0437\u0440\u044b\u0432\u0435 "
            "\u0432 \u0414\u043d\u0435\u043f\u0440\u043e\u043f\u0435\u0442\u0440\u043e\u0432\u0441\u043a\u0435"
        ),
        published_at=datetime(2026, 9, 17, tzinfo=UTC),
        body=(
            "\u0412\u0437\u0440\u044b\u0432 \u043f\u0440\u043e\u0433\u0440\u0435\u043c\u0435\u043b "
            "\u0432 \u0414\u043d\u0435\u043f\u0440\u043e\u043f\u0435\u0442\u0440\u043e\u0432\u0441\u043a\u0435 "
            "\u043d\u0430 \u0423\u043a\u0440\u0430\u0438\u043d\u0435"
        ),
    )
    tass = RawNewsArticle(
        outlet="tass",
        external_id="28122777",
        url="https://tass.ru/proisshestviya/28122777",
        title=(
            "\u0412 \u0414\u043d\u0435\u043f\u0440\u043e\u043f\u0435\u0442\u0440\u043e\u0432\u0441\u043a\u0435 "
            "\u043f\u0440\u043e\u0438\u0437\u043e\u0448\u043b\u0438 \u0432\u0437\u0440\u044b\u0432\u044b"
        ),
        published_at=datetime(2026, 9, 17, tzinfo=UTC),
        body=(
            "\u0412 \u0414\u043d\u0435\u043f\u0440\u043e\u043f\u0435\u0442\u0440\u043e\u0432\u0441\u043a\u043e\u0439 "
            "\u043e\u0431\u043b\u0430\u0441\u0442\u0438 \u0434\u0435\u0439\u0441\u0442\u0432\u0443\u0435\u0442 "
            "\u0440\u0435\u0436\u0438\u043c \u0432\u043e\u0437\u0434\u0443\u0448\u043d\u043e\u0439 \u0442\u0440\u0435\u0432\u043e\u0433\u0438"
        ),
    )
    for article in (ria, tass):
        assert should_skip_foreign_article(article)
        assert resolve_article_geo(db_session, article, street_index=catalog) is None


def test_foreign_wins_even_if_moscow_mentioned(db_session) -> None:
    article = RawNewsArticle(
        outlet="ria",
        external_id="x",
        url="https://ria.ru/x",
        title=(
            "\u041c\u043e\u0441\u043a\u0432\u0430 \u043e\u0442\u0440\u0435\u0430\u0433\u0438\u0440\u043e\u0432\u0430\u043b\u0430 "
            "\u043d\u0430 \u0441\u043e\u0431\u044b\u0442\u0438\u044f \u0432 \u041a\u0438\u0435\u0432\u0435"
        ),
        published_at=datetime(2026, 9, 17, tzinfo=UTC),
        body="ok",
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


def test_extract_street_hints() -> None:
    text = (
        "\u0410\u0432\u0430\u0440\u0438\u044f \u043d\u0430 \u0443\u043b\u0438\u0446\u0435 "
        "\u0422\u0432\u0435\u0440\u0441\u043a\u0430\u044f \u043f\u0435\u0440\u0435\u043a\u0440\u044b\u043b\u0430"
    )
    hints = extract_street_hints(text)
    needle = "\u0442\u0432\u0435\u0440\u0441\u043a\u0430\u044f"
    assert any(needle in h.lower() for h in hints), hints


def test_extract_hint_osm_style_proezd() -> None:
    text = (
        "\u041f\u0440\u043e\u0440\u044b\u0432 \u043d\u0430 "
        "\u0410\u0432\u0442\u043e\u0437\u0430\u0432\u043e\u0434\u0441\u043a\u043e\u043c \u043f\u0440\u043e\u0435\u0437\u0434\u0435"
    )
    hints = extract_street_hints(text)
    assert hints
    assert any(
        "\u0430\u0432\u0442\u043e\u0437\u0430\u0432\u043e\u0434" in h.lower() for h in hints
    ), hints


def test_catalog_morphology_autozavodsky(db_session) -> None:
    street = "1-\u0439 \u0410\u0432\u0442\u043e\u0437\u0430\u0432\u043e\u0434\u0441\u043a\u0438\u0439 \u043f\u0440\u043e\u0435\u0437\u0434"
    _add_row(db_session, street=street, house="2")
    _add_row(db_session, street=street, house="10", lat="55.758")
    catalog = StreetCatalog.load(db_session)
    article = RawNewsArticle(
        outlet="msk1",
        external_id="1",
        url="https://msk1.ru/text/x",
        title=(
            "\u041f\u0440\u043e\u0440\u044b\u0432 \u043d\u0430 "
            "\u0410\u0432\u0442\u043e\u0437\u0430\u0432\u043e\u0434\u0441\u043a\u043e\u043c \u043f\u0440\u043e\u0435\u0437\u0434\u0435"
        ),
        published_at=datetime(2026, 9, 17, tzinfo=UTC),
        body="ok",
    )
    bind = resolve_article_geo(db_session, article, street_index=catalog)
    assert bind is not None
    assert bind.geo_by == "street"


def test_catalog_tverskaya_genitive_with_house(db_session) -> None:
    _add_row(
        db_session,
        street="\u0443\u043b\u0438\u0446\u0430 \u0422\u0432\u0435\u0440\u0441\u043a\u0430\u044f",
        house="1",
    )
    home = _add_row(
        db_session,
        street="\u0443\u043b\u0438\u0446\u0430 \u0422\u0432\u0435\u0440\u0441\u043a\u0430\u044f",
        house="7",
        lat="55.758",
    )
    catalog = StreetCatalog.load(db_session)
    article = RawNewsArticle(
        outlet="msk1",
        external_id="2",
        url="https://msk1.ru/text/x",
        title=(
            "\u041f\u0440\u043e\u0440\u044b\u0432 \u043d\u0430 \u0443\u043b\u0438\u0446\u0435 "
            "\u0422\u0432\u0435\u0440\u0441\u043a\u043e\u0439, \u0434\u043e\u043c 7"
        ),
        published_at=datetime(2026, 9, 17, tzinfo=UTC),
        body="ok",
    )
    bind = resolve_article_geo(db_session, article, street_index=catalog)
    assert bind is not None
    assert bind.geo_by == "home"
    assert bind.address_id == home.id


def test_catalog_leninsky_prospect(db_session) -> None:
    _add_row(
        db_session,
        street="\u041b\u0435\u043d\u0438\u043d\u0441\u043a\u0438\u0439 \u043f\u0440\u043e\u0441\u043f\u0435\u043a\u0442",
        house="1",
    )
    catalog = StreetCatalog.load(db_session)
    article = RawNewsArticle(
        outlet="m24",
        external_id="3",
        url="https://www.m24.ru/news/x",
        title=(
            "\u0414\u0442\u043f \u043d\u0430 \u041b\u0435\u043d\u0438\u043d\u0441\u043a\u043e\u043c "
            "\u043f\u0440\u043e\u0441\u043f\u0435\u043a\u0442\u0435"
        ),
        published_at=datetime(2026, 9, 17, tzinfo=UTC),
        body="ok",
    )
    bind = resolve_article_geo(db_session, article, street_index=catalog)
    assert bind is not None
    assert bind.geo_by == "street"


def test_catalog_ambiguous_refuse(db_session) -> None:
    _add_row(
        db_session,
        street="\u0443\u043b\u0438\u0446\u0430 \u0421\u0430\u0434\u043e\u0432\u0430\u044f",
        house="1",
    )
    _add_row(
        db_session,
        street="\u0443\u043b\u0438\u0446\u0430 \u041d\u043e\u0432\u0430\u044f \u0421\u0430\u0434\u043e\u0432\u0430\u044f",
        house="1",
        lat="55.76",
    )
    catalog = StreetCatalog.load(db_session)
    # Короткий stem, общий для обеих улиц — не угадываем.
    assert catalog._resolve_entry("\u0441\u0430\u0434\u043e\u0432") is None  # noqa: SLF001


def test_resolve_article_geo_from_source_fields(db_session) -> None:
    home = _add_row(
        db_session,
        street="\u0443\u043b\u0438\u0446\u0430 \u0422\u0432\u0435\u0440\u0441\u043a\u0430\u044f",
        house="1",
    )
    catalog = StreetCatalog.load(db_session)
    article = RawNewsArticle(
        outlet="ria",
        external_id="9",
        url="https://ria.ru/x",
        title="No place in title",
        published_at=datetime(2026, 9, 17, tzinfo=UTC),
        body="plain",
        geo_city="\u041c\u043e\u0441\u043a\u0432\u0430",
        geo_street="\u0443\u043b\u0438\u0446\u0430 \u0422\u0432\u0435\u0440\u0441\u043a\u0430\u044f",
        geo_house="1",
    )
    bind = resolve_article_geo(db_session, article, street_index=catalog)
    assert bind is not None
    assert bind.geo_by == "home"
    assert bind.address_id == home.id
