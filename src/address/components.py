"""Разбор и нормализация компонентов адреса (город / улица / дом)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HOUSE_PREFIX = re.compile(
    r"^(?:д\.?|дом)\s*(?P<house>.+)$",
    re.IGNORECASE,
)
_HOUSE_INLINE = re.compile(
    r"\b(?:д\.?|дом)\s+(?P<house>[0-9]+[а-яА-Яa-zA-Z]?(?:\s*[кк]\s*[0-9]+[а-яА-Я]?)?"
    r"(?:\s*[сc]\s*[0-9]+[а-яА-Я]?)?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AddressComponents:
    city: str | None
    street: str | None
    house: str | None


def normalize_component(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.lower().replace("ё", "е").split())
    return text or None


def parse_address_text(address_text: str) -> AddressComponents:
    """
    «Москва, 1-й Автозаводский проезд, д. 2» → city/street/house.
    «Москва» → только city.
    """
    parts = [part.strip() for part in address_text.split(",") if part.strip()]
    if not parts:
        return AddressComponents(None, None, None)

    city = parts[0]
    house: str | None = None
    street_parts: list[str] = []

    for part in parts[1:]:
        match = _HOUSE_PREFIX.match(part)
        if match:
            house = match.group("house").strip()
            continue
        street_parts.append(part)

    street = ", ".join(street_parts) if street_parts else None
    if street and house is None:
        inline = _HOUSE_INLINE.search(street)
        if inline:
            house = inline.group("house").strip()
            street = _HOUSE_INLINE.sub("", street).strip(" ,")

    return AddressComponents(
        city=city or None,
        street=street or None,
        house=house or None,
    )


def build_address_text(*, city: str, street: str | None = None, house: str | None = None) -> str:
    parts = [city.strip()]
    if street and street.strip():
        parts.append(street.strip())
    if house and house.strip():
        parts.append(f"д. {house.strip()}")
    return ", ".join(parts)
