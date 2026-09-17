"""Связка события с адресом: city / street / home."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from address.components import (
    AddressComponents,
    build_address_text,
    normalize_component,
    parse_address_text,
)
from address.db.address import AddressRow
from project.logging_setup import get_logger

logger = get_logger(__name__)

GeoBy = Literal["city", "street", "home"]


class GeoByLevel(StrEnum):
    CITY = "city"
    STREET = "street"
    HOME = "home"


@dataclass(frozen=True, slots=True)
class GeoBind:
    address_id: int
    geo_by: GeoBy


# Дефолт города по outlet (локальные московские СМИ).
OUTLET_DEFAULT_CITY: dict[str, str] = {
    "m24": "Москва",
    "msk1": "Москва",
    "mskagency": "Москва",
}


def get_or_create_city_address(
    session: Session,
    city: str,
    *,
    latitude: float = 55.7558,
    longitude: float = 37.6173,
) -> AddressRow:
    """Точка уровня города (street/house пустые)."""
    city_norm = city.strip()
    existing = session.scalar(
        select(AddressRow).where(
            AddressRow.city == city_norm,
            AddressRow.street.is_(None),
            AddressRow.house.is_(None),
        )
    )
    if existing is not None:
        return existing

    text = build_address_text(city=city_norm)
    by_text = session.scalar(select(AddressRow).where(AddressRow.address_text == text))
    if by_text is not None:
        if by_text.city is None:
            by_text.city = city_norm
        return by_text

    row = AddressRow(
        address_text=text,
        city=city_norm,
        street=None,
        house=None,
        postal_code=None,
        latitude=latitude,
        longitude=longitude,
        is_private=None,
    )
    session.add(row)
    session.flush()
    logger.info("Создан city-адрес id=%s city=%s", row.id, city_norm)
    return row


def _city_rows(session: Session, city: str) -> list[AddressRow]:
    """Строки города; сравнение компонентов — в Python (SQLite lower() не умеет кириллицу)."""
    city_n = normalize_component(city)
    if not city_n:
        return []
    exact = list(session.scalars(select(AddressRow).where(AddressRow.city == city.strip())).all())
    if exact:
        return exact
    return [
        row
        for row in session.scalars(select(AddressRow).where(AddressRow.city.is_not(None))).all()
        if normalize_component(row.city) == city_n
    ]


def find_geo_bind(
    session: Session,
    *,
    city: str | None = None,
    street: str | None = None,
    house: str | None = None,
) -> GeoBind | None:
    """
    Каскад точности:
      city+street+house → home
      city+street → street (любой дом на улице / представитель)
      city → city
    """
    city_n = normalize_component(city)
    street_n = normalize_component(street)
    house_n = normalize_component(house)
    if not city_n or city is None:
        return None

    rows = _city_rows(session, city)

    if street_n and house_n:
        for row in rows:
            if (
                normalize_component(row.street) == street_n
                and normalize_component(row.house) == house_n
                and row.id is not None
            ):
                return GeoBind(address_id=row.id, geo_by=GeoByLevel.HOME)

    if street_n:
        street_rows = [
            row
            for row in rows
            if normalize_component(row.street) == street_n and row.id is not None
        ]
        with_house = [row for row in street_rows if row.house]
        chosen = with_house or street_rows
        if chosen:
            chosen.sort(key=lambda row: row.id or 0)
            return GeoBind(address_id=chosen[0].id, geo_by=GeoByLevel.STREET)  # type: ignore[arg-type]

    city_row = get_or_create_city_address(session, city.strip())
    if city_row.id is not None:
        return GeoBind(address_id=city_row.id, geo_by=GeoByLevel.CITY)
    return None


def components_from_structured(
    *,
    city: str | None = None,
    street: str | None = None,
    house: str | None = None,
    address_text: str | None = None,
) -> AddressComponents:
    if city or street or house:
        return AddressComponents(city=city, street=street, house=house)
    if address_text:
        return parse_address_text(address_text)
    return AddressComponents(None, None, None)
