"""Загрузка явно выбранных адресов территории чата для общего GeoMatcher."""

from collections.abc import Iterable
from itertools import batched

from sqlalchemy import select
from sqlalchemy.orm import Session

from address.db.address import AddressRow
from address.models.address import Address


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
