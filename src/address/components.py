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

_OBVIOUS_HOUSE_SUFFIX = re.compile(
    r"(?:\s+|,\s*)(?:д(?:ом)?\.?\s*)?"
    r"\d+[а-яА-Яa-zA-Z]?\s*"
    r"(?:/\s*\d+[а-яА-Яa-zA-Z]?|"
    r"(?:к(?:орп(?:ус)?)?|[сc](?:тр(?:оение)?)?|стр(?:оение)?|строение)\.?\s*"
    r"\d+[а-яА-Яa-zA-Z]?)\s*$",
    re.IGNORECASE,
)

_CITY_ALIASES = {
    "moscow": "Москва",
    "москва": "Москва",
    "город москва": "Москва",
    "москва город": "Москва",
}
_INVALID_LOCALITIES = {
    "город не указан",
    "район не указан",
    "не указан",
    "unknown",
}
_DISTRICT_PREFIXES = (
    "вн.тер.г. муниципальный округ ",
    "внутригородская территория города федерального значения ",
    "внутригородское муниципальное образование ",
    "муниципальный округ ",
    "район ",
)


def clean_city_label(value: str | None) -> str | None:
    """Привести служебные/английские подписи города к UI-виду."""
    if not value:
        return None
    text = " ".join(value.split()).strip()
    folded = text.casefold().replace("ё", "е")
    if folded in _INVALID_LOCALITIES:
        return None
    return _CITY_ALIASES.get(folded, text)


def clean_district_label(value: str | None, *, city: str | None = None) -> str | None:
    """Очистить locality из источника, не превращая мусор в район."""
    if not value:
        return None
    text = " ".join(value.split()).strip(" ,")
    folded = text.casefold().replace("ё", "е")
    city_folded = (clean_city_label(city) or "").casefold().replace("ё", "е")
    if folded in _INVALID_LOCALITIES or folded in _CITY_ALIASES or folded == city_folded:
        return None
    for prefix in _DISTRICT_PREFIXES:
        if folded.startswith(prefix):
            text = text[len(prefix) :].strip(" -—")
            folded = text.casefold().replace("ё", "е")
            break
    if not text or folded in _INVALID_LOCALITIES or folded in _CITY_ALIASES:
        return None
    # Это типичные OSM locality, но не административные районы. Оставлять их
    # отдельными кнопками означает показывать пользователю ЖК/дорогу как район.
    noisy = (
        "жилой комплекс",
        "снт ",
        "дск ",
        "мкад",
        "московская железная дорога",
        "мжд ",
        "километр",
    )
    if any(marker in folded for marker in noisy):
        return None
    return text


@dataclass(frozen=True, slots=True)
class AddressComponents:
    city: str | None
    district: str | None
    street: str | None
    house: str | None


def normalize_component(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.lower().replace("ё", "е").split())
    return text or None


def _normalize_house_suffix(value: str | None) -> str:
    if not value:
        return ""
    text = value.casefold().replace("ё", "е")
    text = re.sub(r"\s+", "", text)
    return (
        text.replace("корпус", "к")
        .replace("корп", "к")
        .replace("строение", "с")
        .replace("стр", "с")
    )


def clean_street_house_suffix(street: str | None, house: str | None) -> str | None:
    """Убрать номер дома, если источник случайно продублировал его в addr:street.

    Сначала используем фактический ``house``. Дополнительно чистим очевидный
    хвост с корпусом/строением даже при грязных несовпадающих данных источника:
    ``Сельскохозяйственная улица 4 с18`` → ``Сельскохозяйственная улица``.
    Обычные числовые названия улиц (``улица 1905 года``, ``проезд 607``)
    этот fallback не затрагивает.
    """
    if not street:
        return street

    street = street.strip()
    if not street:
        return street

    house_key = _normalize_house_suffix(house)
    if house_key:
        parts = street.split()
        # Номер дома обычно занимает 1–4 токена: ``15``, ``15 к1``, ``15 стр 2``.
        for start in range(max(1, len(parts) - 4), len(parts)):
            suffix = " ".join(parts[start:])
            if _normalize_house_suffix(suffix) != house_key:
                continue
            candidate = " ".join(parts[:start]).strip(" ,")
            if candidate:
                return candidate

    # В OSM встречаются строки, где addr:street уже содержит другой дом/строение,
    # поэтому сравнение с row.house не помогает. Снимаем только недвусмысленный
    # составной номер (4 к1 / 4 с18 / 4 стр 2 / 4/1), но не голое число.
    match = _OBVIOUS_HOUSE_SUFFIX.search(street)
    if match:
        candidate = street[: match.start()].strip(" ,")
        if candidate:
            return candidate

    return street


def parse_address_text(address_text: str) -> AddressComponents:
    """
    «Москва, 1-й Автозаводский проезд, д. 2» → city/street/house.
    «Москва» → только city.
    """
    parts = [part.strip() for part in address_text.split(",") if part.strip()]
    if not parts:
        return AddressComponents(None, None, None, None)

    city = parts[0]
    house: str | None = None
    street_parts: list[str] = []

    for part in parts[1:]:
        match = _HOUSE_PREFIX.match(part)
        if match:
            house = match.group("house").strip()
            continue
        street_parts.append(part)

    # prepare_osm пишет locality между городом и улицей. Последняя не-house
    # часть — улица, предыдущие части — район/поселение.
    street = street_parts[-1] if street_parts else None
    district = ", ".join(street_parts[:-1]) if len(street_parts) > 1 else None
    if street and house is not None:
        street = clean_street_house_suffix(street, house)
    if street and house is None:
        inline = _HOUSE_INLINE.search(street)
        if inline:
            house = inline.group("house").strip()
            street = _HOUSE_INLINE.sub("", street).strip(" ,")

    return AddressComponents(
        city=city or None,
        district=district or None,
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
