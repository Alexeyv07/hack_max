"""Общий локальный геопоиск. На вход — адреса только территории текущего чата."""

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from rapidfuzz.fuzz import ratio

from address.models.address import Address

_STREET_TYPES = {
    "улица",
    "проспект",
    "проезд",
    "переулок",
    "шоссе",
    "бульвар",
    "набережная",
    "площадь",
    "аллея",
}
_ALIASES = {
    "ул": "улица",
    "пр-т": "проспект",
    "просп": "проспект",
    "пр-д": "проезд",
    "пер": "переулок",
    "ш": "шоссе",
    "б-р": "бульвар",
    "наб": "набережная",
    "пл": "площадь",
}
_POSTCODE = re.compile(r"(?<!\w)[0-9]{6}(?!\w)")
_NUMBER = r"[0-9]+[а-я]?(?:/[0-9]+[а-я]?)?"
_HOUSE = re.compile(
    rf"\bдом\s+({_NUMBER})(?:\s+корпус\s+({_NUMBER}))?(?:\s+строение\s+({_NUMBER}))?(?![\w/])"
)


def normalize_address(text: str) -> str:
    text = text.lower().replace("ё", "е")
    for short, full in _ALIASES.items():
        text = re.sub(rf"\b{re.escape(short)}\b\.?", full + " ", text)
    for short, full in (
        ("д|дом", "дом"),
        ("к|корп|корпус", "корпус"),
        ("с|стр|строение", "строение"),
    ):
        text = re.sub(rf"\b(?:{short})\.?\s*(?=[0-9])", full + " ", text)
    return " ".join(re.sub(r"[^\w/]+", " ", text).split())


@dataclass(frozen=True, slots=True)
class GeoResult:
    latitude: Decimal | None
    longitude: Decimal | None
    scope: Literal["address", "chat", "city"]
    method: Literal["postcode", "fuzzy", "fallback"]
    score: float = 0
    address_text: str | None = None


@dataclass(frozen=True, slots=True)
class _Entry:
    address: Address
    street: str
    street_type: str | None
    house: tuple[str | None, ...] | None


def _entry(address: Address) -> _Entry:
    normalized = normalize_address(address.address_text)
    house = _HOUSE.search(normalized)
    # В справочнике улица — отдельный компонент перед «д. / дом».
    before_house = re.split(r"\b(?:д\.?|дом)\s*(?=[0-9])", address.address_text, flags=re.I)[0]
    components = [normalize_address(part) for part in before_house.split(",") if part.strip()]
    street = next((part for part in reversed(components) if set(part.split()) & _STREET_TYPES), "")
    words = street.split()
    street_type = next((word for word in words if word in _STREET_TYPES), None)
    if street_type:
        # Поддерживаем также «Москва ул. Ленина» без запятых.
        position = words.index(street_type)
        words = words[position + 1 :] if position < len(words) - 1 else words[:position]
    return _Entry(address, " ".join(words), street_type, house.groups() if house else None)


def _street_score(street: str, words: list[str]) -> float:
    if not street:
        return 0
    length = len(street.split())
    numbers = re.findall(r"[0-9]+", street)
    return max(
        (
            ratio(street, " ".join(words[i : i + length]))
            for i in range(len(words) - length + 1)
            if re.findall(r"[0-9]+", " ".join(words[i : i + length])) == numbers
        ),
        default=0,
    )


class GeoMatcher:
    """Снимок адресов города/района. Создать после загрузки из БД, переиспользовать."""

    def __init__(self, addresses: Iterable[Address], *, threshold: float = 90, margin: float = 5):
        if not 0 < threshold <= 100 or not 0 < margin <= 100:
            raise ValueError("threshold и margin должны быть в диапазоне (0, 100]")
        self.threshold, self.margin = threshold, margin
        self.entries = [
            _entry(address) for address in {a.address_text: a for a in addresses}.values()
        ]
        self.by_postcode = defaultdict(list)
        for entry in self.entries:
            if entry.address.postal_code:
                self.by_postcode[entry.address.postal_code].append(entry)

    def resolve(
        self, text: str, *, chat_coordinates: tuple[Decimal, Decimal] | None = None
    ) -> GeoResult:
        fallback = GeoResult(
            *(chat_coordinates or (None, None)),
            scope="chat" if chat_coordinates else "city",
            method="fallback",
        )
        normalized = normalize_address(text)
        houses = list(_HOUSE.finditer(normalized))
        postcodes = set(_POSTCODE.findall(text))
        if len(houses) > 1 or len(postcodes) > 1 or ("дом" in normalized.split() and not houses):
            return fallback
        remaining = _POSTCODE.sub(" ", _HOUSE.sub(" ", normalized))
        if {"дом", "корпус", "строение"} & set(remaining.split()):
            return fallback
        candidates = self.by_postcode.get(next(iter(postcodes)), []) if postcodes else self.entries
        if houses:
            candidates = [entry for entry in candidates if entry.house == houses[0].groups()]
        types = set(normalized.split()) & _STREET_TYPES
        if types:
            candidates = [entry for entry in candidates if entry.street_type in types]
        if not houses:
            # Не выдаём дом 10 по фразе «Ленина 99», которую не смогли разобрать.
            numbers = re.findall(r"[0-9]+", remaining)
            candidates = [
                entry for entry in candidates if re.findall(r"[0-9]+", entry.street) == numbers
            ]
        if postcodes and len(candidates) == 1 and not types:
            address = candidates[0].address
            return GeoResult(
                address.latitude,
                address.longitude,
                "address",
                "postcode",
                100,
                address.address_text,
            )
        words = [word for word in _HOUSE.sub(" ", normalized).split() if word not in _STREET_TYPES]
        scores = {
            street: _street_score(street, words)
            for street in {entry.street for entry in candidates}
        }
        ranked = sorted(
            ((scores[entry.street], entry) for entry in candidates),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if not ranked or ranked[0][0] < self.threshold:
            return fallback
        if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < self.margin:
            return fallback
        score, entry = ranked[0]
        address = entry.address
        return GeoResult(
            address.latitude,
            address.longitude,
            "address",
            "postcode" if postcodes else "fuzzy",
            score,
            address.address_text,
        )
