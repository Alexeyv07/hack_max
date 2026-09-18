"""Поиск дома по пользовательскому вводу для onboarding чата."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from address.components import normalize_component, parse_address_text
from address.db.address import AddressRow
from address.db.queries import address_from_row
from address.models.address import Address

_POSTCODE = re.compile(r"^[0-9]{6}$")
_TRAILING_HOUSE = re.compile(
    r"^(?P<street>.+?)\s+(?P<house>[0-9]+[а-яА-Яa-zA-Z]?(?:/[0-9]+[а-яА-Яa-zA-Z]?)?)$"
)


class AddressNotFoundError(ValueError):
    """В справочнике нет конкретного дома."""


class AddressAmbiguousError(ValueError):
    """Ввод соответствует нескольким домам и требует уточнения."""


class PrivateHouseError(ValueError):
    """Чаты частных домов не входят в текущий сценарий."""


def _finish(rows: list[AddressRow]) -> Address:
    homes = [row for row in rows if row.house]
    if not homes:
        raise AddressNotFoundError("Дом не найден. Введите полный адрес с номером дома.")

    public_rows = [row for row in homes if row.is_private is not True]
    if not public_rows:
        raise PrivateHouseError("Чаты частных домов пока не поддерживаются.")
    if len(public_rows) > 1:
        raise AddressAmbiguousError("Найдено несколько домов. Уточните полный адрес.")
    return address_from_row(public_rows[0])


def _normalized_component_rows(
    session: Session, *, city: str, street: str, house: str
) -> list[AddressRow]:
    city_n = normalize_component(city)
    street_n = normalize_component(street)
    house_n = normalize_component(house)
    candidates = session.scalars(
        select(AddressRow).where(AddressRow.house.is_not(None), AddressRow.house == house.strip())
    ).all()
    return [
        row
        for row in candidates
        if normalize_component(row.city) == city_n
        and normalize_component(row.street) == street_n
        and normalize_component(row.house) == house_n
    ]


def resolve_home_address(session: Session, user_input: str) -> Address:
    """Найти дом по полному текстовому адресу или шестизначному индексу.

    Один индекс может соответствовать нескольким домам, поэтому неоднозначный
    результат возвращается как ошибка для последующего уточнения пользователем.
    Выбор точки на карте относится к KAN-18.
    """
    text = " ".join(user_input.strip().split())
    if not text:
        raise AddressNotFoundError("Введите адрес.")
    if len(text) > 1000:
        raise AddressNotFoundError("Адрес слишком длинный.")

    if _POSTCODE.fullmatch(text):
        rows = list(
            session.scalars(
                select(AddressRow).where(
                    AddressRow.postal_code == text,
                    AddressRow.house.is_not(None),
                )
            )
        )
        if len(rows) > 1:
            raise AddressAmbiguousError(
                "Этот индекс относится к нескольким домам. Введите полный адрес."
            )
        return _finish(rows)

    exact = session.scalar(select(AddressRow).where(AddressRow.address_text == text))
    if exact is not None:
        return _finish([exact])

    # Текущий локальный справочник KAN-6 — московский: город можно не печатать.
    candidate_text = text
    first_part = text.split(",", 1)[0]
    if normalize_component(first_part) != "москва":
        candidate_text = f"Москва, {text}"

    components = parse_address_text(candidate_text)
    city = components.city
    street = components.street
    house = components.house

    # Удобная форма без «д.»: «Сельскохозяйственная улица 15/1».
    if city and street and not house:
        trailing = _TRAILING_HOUSE.match(street)
        if trailing:
            street = trailing.group("street").strip(" ,")
            house = trailing.group("house")

    if not city or not street or not house:
        raise AddressNotFoundError("Введите полный адрес: город, улица и номер дома.")

    rows = list(
        session.scalars(
            select(AddressRow).where(
                AddressRow.city == city.strip(),
                AddressRow.street == street.strip(),
                AddressRow.house == house.strip(),
            )
        )
    )
    if not rows:
        rows = _normalized_component_rows(session, city=city, street=street, house=house)
    return _finish(rows)
