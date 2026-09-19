"""Геопривязка новости: только Москва / улицы справочника; чужие регионы → null."""

from __future__ import annotations

from sqlalchemy.orm import Session

from address.db.queries import load_addresses_by_postcodes
from address.geocoding import GeoMatcher
from address.models.address import Address
from address.resolve import OUTLET_DEFAULT_CITY, GeoBind, GeoByLevel, find_geo_bind
from address.street_catalog import StreetCatalog
from parse_news.models.article import RawNewsArticle
from parser_common.geo_text import (
    extract_house,
    extract_postcodes,
    extract_street_hints,
    is_foreign_geo,
    is_moscow_context,
    is_non_moscow_geo,
)
from project.logging_setup import get_logger

logger = get_logger(__name__)

MoscowStreetIndex = StreetCatalog


def article_text(article: RawNewsArticle) -> str:
    return "\n".join(part for part in (article.title, article.body or "") if part)


def should_skip_foreign_article(article: RawNewsArticle) -> bool:
    return is_foreign_geo(article_text(article))


def resolve_article_geo(
    session: Session,
    article: RawNewsArticle,
    *,
    street_index: StreetCatalog | None = None,
) -> GeoBind | None:
    """
    Только Москва и её улицы. Чужой город/страна → None (без дефолта Москвы).

    Каскад:
      1) geo_* источника (город должен быть Москвой);
      2) текст: индекс / StreetCatalog (локальный outlet или явная Москва) /
         явное «Москва»;
      3) дефолт Москвы — только m24/msk1/mskagency без чужой географии.
    """
    text = article_text(article)
    if is_non_moscow_geo(text):
        return None

    moscow = is_moscow_context(text)
    local_outlet = article.outlet in OUTLET_DEFAULT_CITY

    bind = _resolve_from_source_fields(
        session,
        article,
        street_index=street_index,
        allow_moscow=True,
    )
    if bind is not None:
        return bind

    bind = _resolve_from_text(
        session,
        article,
        street_index=street_index,
        text=text,
        allow_streets=local_outlet or moscow,
    )
    if bind is not None:
        return bind

    if local_outlet:
        return find_geo_bind(session, city=OUTLET_DEFAULT_CITY[article.outlet])
    return None


def resolve_article_address(
    session: Session,
    article: RawNewsArticle,
    *,
    street_index: StreetCatalog | None = None,
) -> int | None:
    bind = resolve_article_geo(session, article, street_index=street_index)
    return bind.address_id if bind else None


def _resolve_from_source_fields(
    session: Session,
    article: RawNewsArticle,
    *,
    street_index: StreetCatalog | None,
    allow_moscow: bool,
) -> GeoBind | None:
    if not (article.geo_city or article.geo_street or article.geo_house):
        return None

    city = (article.geo_city or "").strip()
    if city and not is_moscow_context(city):
        return None
    if not allow_moscow and not city:
        return None

    if article.geo_street and street_index is not None and allow_moscow:
        hit = street_index.lookup(article.geo_street, house=article.geo_house)
        if hit is not None:
            geo_by = GeoByLevel.HOME if hit.house else GeoByLevel.STREET
            return GeoBind(address_id=hit.address_id, geo_by=geo_by)

    bind = find_geo_bind(
        session,
        city=city or "Москва",
        street=article.geo_street,
        house=article.geo_house,
    )
    if bind is not None and bind.geo_by != GeoByLevel.CITY:
        return bind
    if city and not article.geo_street:
        return find_geo_bind(session, city=city)
    return None


def _resolve_from_text(
    session: Session,
    article: RawNewsArticle,
    *,
    street_index: StreetCatalog | None,
    text: str,
    allow_streets: bool,
) -> GeoBind | None:
    if not text.strip():
        return None

    if allow_streets:
        postcodes = extract_postcodes(text)
        if postcodes:
            addresses = load_addresses_by_postcodes(session, postcodes)
            address_id = _match_address(text, addresses)
            if address_id is not None:
                return GeoBind(address_id=address_id, geo_by=GeoByLevel.HOME)

        hints = extract_street_hints(text)
        house = extract_house(text)
        if hints and street_index is not None:
            hit = street_index.lookup_hints(hints, house=house)
            if hit is not None:
                geo_by = GeoByLevel.HOME if (house and hit.house) else GeoByLevel.STREET
                return GeoBind(address_id=hit.address_id, geo_by=geo_by)

    if is_moscow_context(text):
        return find_geo_bind(session, city="Москва")
    return None


def _match_address(text: str, addresses: list[Address]) -> int | None:
    if not addresses:
        return None
    if len(addresses) > 800:
        addresses = addresses[:800]
    matcher = GeoMatcher(addresses)
    geo = matcher.resolve(text)
    if geo.method == "fallback" or geo.address_id is None:
        return None
    return geo.address_id


# Re-export text helpers for tests that imported from this module.
__all__ = [
    "MoscowStreetIndex",
    "article_text",
    "extract_house",
    "extract_postcodes",
    "extract_street_hints",
    "is_foreign_geo",
    "is_moscow_context",
    "is_non_moscow_geo",
    "resolve_article_address",
    "resolve_article_geo",
    "should_skip_foreign_article",
]
