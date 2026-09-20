"""Геопривязка объявлений УК: Москва; fan-out по всем найденным улицам."""

from __future__ import annotations

from sqlalchemy.orm import Session

from address.resolve import OUTLET_DEFAULT_CITY, GeoBind, GeoByLevel, find_geo_bind
from address.street_catalog import StreetCatalog, StreetHit
from parse_mc.models.notice import RawMcNotice
from parser_common.geo_text import (
    extract_house,
    is_foreign_geo,
    is_non_moscow_geo,
)
from parser_common.place_ner import collect_location_hints
from project.logging_setup import get_logger

logger = get_logger(__name__)

MC_OUTLET_DEFAULT_CITY: dict[str, str] = {
    "pik_comfort": "Москва",
    "granel": "Москва",
    "zhil_nagatino": "Москва",
    "gbu_portal": "Москва",
    "moek": "Москва",
}


def notice_text(notice: RawMcNotice) -> str:
    parts = [notice.title, notice.body or "", *notice.streets]
    return "\n".join(p for p in parts if p)


def should_skip_foreign_notice(notice: RawMcNotice) -> bool:
    return is_foreign_geo(notice_text(notice))


def resolve_notice_geos(
    session: Session,
    notice: RawMcNotice,
    *,
    street_index: StreetCatalog | None = None,
) -> list[GeoBind]:
    """
    Вернуть **все** уникальные привязки (улица/дом).

    Если объявление касается нескольких улиц — по одной GeoBind на улицу
    (воркер создаст отдельное событие на каждую).
    """
    text = notice_text(notice)
    if is_non_moscow_geo(text) and not notice.streets:
        return []

    hints: list[str] = list(notice.streets)
    hints.extend(collect_location_hints(text))
    hints = list(dict.fromkeys(h for h in hints if h and h.strip()))

    house = notice.geo_house or extract_house(text)
    hits: list[StreetHit] = []
    if hints and street_index is not None:
        hits = street_index.lookup_all_hints(hints, house=house)

    binds: list[GeoBind] = []
    seen_ids: set[int] = set()
    for hit in hits:
        if hit.address_id in seen_ids:
            continue
        seen_ids.add(hit.address_id)
        geo_by = GeoByLevel.HOME if hit.house else GeoByLevel.STREET
        binds.append(GeoBind(address_id=hit.address_id, geo_by=geo_by))

    if binds:
        return binds

    if notice.geo_street and street_index is not None:
        hit = street_index.lookup(notice.geo_street, house=notice.geo_house)
        if hit is not None:
            geo_by = GeoByLevel.HOME if hit.house else GeoByLevel.STREET
            return [GeoBind(address_id=hit.address_id, geo_by=geo_by)]

    city = (
        notice.geo_city
        or MC_OUTLET_DEFAULT_CITY.get(notice.outlet)
        or OUTLET_DEFAULT_CITY.get(notice.outlet)
    )
    if city and not is_non_moscow_geo(text):
        bind = find_geo_bind(session, city=city)
        if bind is not None:
            return [bind]
    return []
