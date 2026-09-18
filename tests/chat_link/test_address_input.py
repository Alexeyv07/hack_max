"""Ввод адреса KAN-7 через handlers модуля address."""

from __future__ import annotations

from decimal import Decimal

import pytest

from address.db import AddressRow
from address.handlers import (
    AddressAmbiguousError,
    AddressNotFoundError,
    PrivateHouseError,
    resolve_home_address,
)


def _address(
    db_session,
    *,
    text,
    postcode="129226",
    private=False,
    street="Сельскохозяйственная улица",
    house="15/1",
):
    row = AddressRow(
        address_text=text,
        postal_code=postcode,
        latitude=Decimal("55.8350000"),
        longitude=Decimal("37.6350000"),
        is_private=private,
        city="Москва",
        street=street,
        house=house,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_full_address_and_short_moscow_form(db_session) -> None:
    row = _address(db_session, text="Москва, Сельскохозяйственная улица, д. 15/1")
    assert resolve_home_address(db_session, row.address_text).id == row.id
    assert resolve_home_address(db_session, "Сельскохозяйственная улица, д. 15/1").id == row.id


def test_postcode_must_point_to_one_house(db_session) -> None:
    first = _address(db_session, text="Москва, Тестовая улица, д. 1", house="1")
    _address(db_session, text="Москва, Тестовая улица, д. 2", house="2")
    with pytest.raises(AddressAmbiguousError, match="нескольким домам"):
        resolve_home_address(db_session, first.postal_code)


def test_private_house_is_rejected(db_session) -> None:
    row = _address(
        db_session,
        text="Москва, Частная улица, д. 7",
        postcode="129227",
        private=True,
        street="Частная улица",
        house="7",
    )
    with pytest.raises(PrivateHouseError):
        resolve_home_address(db_session, row.address_text)


def test_incomplete_address_is_rejected(db_session) -> None:
    with pytest.raises(AddressNotFoundError, match="полный адрес"):
        resolve_home_address(db_session, "Москва, Сельскохозяйственная улица")
