"""Загрузка явно выбранных адресов территории чата для общего GeoMatcher."""

from collections.abc import Iterable
from itertools import batched

from sqlalchemy import select
from sqlalchemy.orm import Session

from address.db.address import AddressRow
from address.models.address import Address


def load_addresses_by_postcodes(session: Session, postcodes: Iterable[str]) -> list[Address]:
    """Загрузить адреса по почтовым индексам (для geo в parse_news)."""
    addresses: list[Address] = []
    for codes in batched(dict.fromkeys(postcodes), 1000):
        for row in session.scalars(select(AddressRow).where(AddressRow.postal_code.in_(codes))):
            addresses.append(
                Address(
                    id=row.id,
                    postal_code=row.postal_code,
                    address_text=row.address_text,
                    latitude=row.latitude,
                    longitude=row.longitude,
                    is_private=row.is_private,
                )
            )
    return addresses


def load_addresses(session: Session, *, address_texts: Iterable[str]) -> list[Address]:
    """Ключи передаёт вызывающий модуль; пустой набор не расширяем до всей БД."""
    addresses = []
    for keys in batched(dict.fromkeys(address_texts), 1000):
        for row in session.scalars(select(AddressRow).where(AddressRow.address_text.in_(keys))):
            addresses.append(
                Address(
                    id=row.id,
                    postal_code=row.postal_code,
                    address_text=row.address_text,
                    latitude=row.latitude,
                    longitude=row.longitude,
                    is_private=row.is_private,
                )
            )
    return addresses
