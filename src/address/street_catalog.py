"""Каталог улиц: stemming + fuzzy lookup по справочнику addresses."""

from __future__ import annotations

import heapq
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from address.components import (
    clean_city_label,
    clean_district_label,
    clean_street_house_suffix,
    parse_address_text,
)
from address.db.address import AddressRow
from address.geocoding import normalize_address
from project.logging_setup import get_logger

logger = get_logger(__name__)

_STREET_TYPES = frozenset(
    {
        "улица",
        "проспект",
        "проезд",
        "переулок",
        "шоссе",
        "бульвар",
        "набережная",
        "площадь",
        "аллея",
        "тупик",
        "квартал",
        "микрорайон",
        "линия",
    }
)

_ORDINAL = re.compile(r"^\d+-?[йяе]$", re.IGNORECASE)
_HOUSE_BASE = re.compile(r"^(\d+[а-яa-z]?)", re.IGNORECASE)

_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_SEARCH_SEPARATOR_RE = re.compile(r"[^0-9a-zа-я]+", re.IGNORECASE)


def normalize_ui_text(value: str | None) -> str:
    """Нормализация подписей/поиска UI: Unicode, регистр, zero-width, ё/е."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = _INVISIBLE_RE.sub("", text)
    return " ".join(text.casefold().replace("ё", "е").split()).strip()


def normalize_search_text(value: str | None) -> str:
    """Поисковый ключ: Unicode + адресные сокращения + минимум пунктуации."""
    normalized = normalize_ui_text(value)
    if not normalized:
        return ""
    # Частый живой ввод: «15к1», «15с1», «15/1» без пробелов.
    # Для поиска корпус/строение/слеш считаем взаимозаменяемыми обозначениями
    # вторичной части номера дома. Само значение в справочнике не меняем.
    normalized = re.sub(r"(?<=\d)\s*/\s*(?=\d)", " корпус ", normalized)
    normalized = re.sub(r"(?<=\d)к(?:орп(?:ус)?)?\.?\s*(?=\d)", " корпус ", normalized)
    normalized = re.sub(r"(?<=\d)с(?:тр(?:оение)?)?\.?\s*(?=\d)", " строение ", normalized)
    normalized = normalize_address(normalized)
    return " ".join(_SEARCH_SEPARATOR_RE.sub(" ", normalized).split())


_SEARCH_STRUCTURE_TOKENS = _STREET_TYPES | {
    "город",
    "район",
    "дом",
    "корпус",
    "строение",
}
_SEARCH_STOP_TOKENS = _SEARCH_STRUCTURE_TOKENS | {
    "г",
    "адрес",
    "на",
    "в",
    "по",
    "у",
    "мой",
    "моя",
    "мое",
    "живу",
    "проживаю",
    "найди",
    "найти",
}
_SEARCH_NUMBER_TOKEN = re.compile(r"^\d+[а-яa-z]?$", re.IGNORECASE)
_ORDINAL_SUFFIX_TOKENS = frozenset({"й", "я", "е"})


@dataclass(frozen=True, slots=True)
class _SearchQueryParts:
    full_text: str
    text_without_house: str
    house: str | None
    explicit_house: bool


def _meaningful_search_tokens(value: str) -> list[str]:
    tokens = [token for token in value.split() if token not in _SEARCH_STOP_TOKENS]
    return tokens or value.split()


def _search_query_parts(value: str) -> _SearchQueryParts:
    """Разделить свободный ввод на текст адреса и вероятный номер дома.

    Явные ``дом/корпус/строение`` считаются строгой подсказкой. Голое число
    считается лишь эвристикой: при ранжировании одновременно проверяется вариант,
    что это часть названия улицы (например, «улица 1905 года»).
    """
    tokens = value.split()
    removed: set[int] = set()
    house: str | None = None
    explicit = False

    def number_at(index: int) -> str | None:
        if 0 <= index < len(tokens) and _SEARCH_NUMBER_TOKEN.fullmatch(tokens[index]):
            return tokens[index]
        return None

    # Явная форма: «дом 15 корпус 1 строение 2».
    if "дом" in tokens:
        marker = tokens.index("дом")
        base = number_at(marker + 1)
        if base:
            explicit = True
            removed.update({marker, marker + 1})
            parts = [base]
            cursor = marker + 2
            while cursor + 1 < len(tokens):
                label = tokens[cursor]
                number = number_at(cursor + 1)
                if label not in {"корпус", "строение"} or not number:
                    break
                parts.append(("к" if label == "корпус" else "с") + number)
                removed.update({cursor, cursor + 1})
                cursor += 2
            house = "".join(parts)

    # Частая форма без «дом»: «15 корпус 1» / «15к1».
    if house is None:
        for marker_name, short in (("корпус", "к"), ("строение", "с")):
            if marker_name not in tokens:
                continue
            marker = tokens.index(marker_name)
            suffix = number_at(marker + 1)
            base_index = next(
                (index for index in range(marker - 1, -1, -1) if number_at(index)),
                None,
            )
            if base_index is None or not suffix:
                continue
            base = tokens[base_index]
            explicit = True
            removed.update({base_index, marker, marker + 1})
            house = f"{base}{short}{suffix}"

            # Если после корпуса указан ещё и номер строения, учитываем его тоже.
            other = "строение" if marker_name == "корпус" else "корпус"
            if other in tokens:
                other_index = tokens.index(other)
                other_number = number_at(other_index + 1)
                if other_number:
                    suffix_short = "с" if other == "строение" else "к"
                    house += f"{suffix_short}{other_number}"
                    removed.update({other_index, other_index + 1})
            break

    # Голый номер дома. Не принимаем «1-я/2-й» за дом. Это НЕ строгая
    # интерпретация: ниже scorer всё равно проверит число как часть названия улицы.
    if house is None:
        numeric_indexes = []
        for index, token in enumerate(tokens):
            if not _SEARCH_NUMBER_TOKEN.fullmatch(token):
                continue
            if index + 1 < len(tokens) and tokens[index + 1] in _ORDINAL_SUFFIX_TOKENS:
                continue
            numeric_indexes.append(index)
        has_words = any(re.search(r"[а-яa-z]", token, re.IGNORECASE) for token in tokens)
        candidate: int | None = None
        if has_words and len(numeric_indexes) == 1:
            candidate = numeric_indexes[0]
        elif has_words and numeric_indexes and numeric_indexes[-1] == len(tokens) - 1:
            candidate = numeric_indexes[-1]
        if candidate is not None:
            house = tokens[candidate]
            removed.add(candidate)

    full_tokens = _meaningful_search_tokens(value)
    without_house = [
        token
        for index, token in enumerate(tokens)
        if index not in removed and token not in _SEARCH_STOP_TOKENS
    ]
    return _SearchQueryParts(
        full_text=" ".join(full_tokens),
        text_without_house=" ".join(without_house),
        house=house,
        explicit_house=explicit,
    )


# Короткие окончания: длинные «ском/ского» иначе дают разный корень у «-ский» vs «-ском».
_STEM_SUFFIXES = (
    "ого",
    "ему",
    "ому",
    "ыми",
    "ими",
    "ых",
    "их",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ой",
    "ый",
    "ий",
    "ом",
    "ем",
    "ую",
    "юю",
    "ам",
    "ям",
    "ах",
    "ях",
)


@dataclass(frozen=True, slots=True)
class CatalogAddress:
    id: int
    address_text: str
    postal_code: str | None
    city: str
    district: str | None
    street: str
    house: str
    latitude: float
    longitude: float


@dataclass(slots=True)
class StreetEntry:
    city: str
    canonical: str
    pin_id: int
    houses: dict[str, int] = field(default_factory=dict)
    keys: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class StreetHit:
    city: str
    canonical: str
    pin_id: int
    address_id: int
    score: float
    house: str | None = None


def stem_token(token: str) -> str:
    """Срезать типичные окончания; корень не короче 4 символов."""
    word = token.lower().replace("ё", "е")
    if len(word) < 5:
        return word
    for suffix in _STEM_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def normalize_house(value: str | None) -> str | None:
    if not value:
        return None
    text = value.lower().replace("ё", "е").strip()
    text = re.sub(r"\s+", "", text)
    text = (
        text.replace("корпус", "к")
        .replace("корп", "к")
        .replace("строение", "с")
        .replace("стр", "с")
    )
    return text or None


def normalize_house_search(value: str | None) -> str | None:
    """Ключ только для свободного поиска: 15к1 == 15с1 == 15/1."""
    norm = normalize_house(value)
    if not norm:
        return None
    # Не смешиваем этот ключ с точным house lookup: в БД корпус и строение могут
    # быть разными объектами. Эквивалентность нужна только при поиске пользователем.
    return re.sub(r"(?<=\d)[кс/](?=\d)", "/", norm)


def house_lookup_keys(value: str | None) -> list[str]:
    """Варианты ключа дома: exact, затем базовый номер."""
    norm = normalize_house(value)
    if not norm:
        return []
    keys = [norm]
    match = _HOUSE_BASE.match(norm)
    if match:
        base = match.group(1).lower()
        if base not in keys:
            keys.append(base)
    # «2к1» → также «2»
    compact = re.sub(r"[кс].*$", "", norm)
    if compact and compact not in keys:
        keys.append(compact)
    return keys


def street_alias_keys(street: str) -> set[str]:
    """Набор ключей для одной улицы (полное / без типа / без ординала / stem)."""
    normalized = normalize_address(street)
    if not normalized:
        return set()
    tokens = normalized.split()
    keys: set[str] = {normalized}

    without_type = [t for t in tokens if t not in _STREET_TYPES]
    if without_type:
        keys.add(" ".join(without_type))

    without_ord = [t for t in without_type if not _ORDINAL.match(t)]
    if without_ord:
        keys.add(" ".join(without_ord))

    stemmed = [stem_token(t) for t in without_type]
    if stemmed:
        keys.add(" ".join(stemmed))
    stemmed_no_ord = [stem_token(t) for t in without_ord]
    if stemmed_no_ord:
        keys.add(" ".join(stemmed_no_ord))

    # Одиночные значимые токены (тверская → тверск)
    for token in without_ord:
        if len(token) >= 4 and not token.isdigit():
            keys.add(token)
            keys.add(stem_token(token))

    return {k for k in keys if k}


def hint_keys(hint: str) -> set[str]:
    return street_alias_keys(hint)


class StreetCatalog:
    """Снимок улиц города: exact → contains → fuzzy (rapidfuzz)."""

    def __init__(
        self,
        entries: list[StreetEntry],
        *,
        addresses: list[CatalogAddress] | None = None,
        fuzzy_threshold: float = 82,
        fuzzy_margin: float = 5,
    ) -> None:
        self.entries = entries
        self.addresses = addresses or []
        self.fuzzy_threshold = fuzzy_threshold
        self.fuzzy_margin = fuzzy_margin
        self._address_by_id = {row.id: row for row in self.addresses}
        self._address_search_items = [
            (
                row,
                normalize_search_text(
                    " ".join(
                        part
                        for part in (
                            row.city,
                            row.district,
                            row.street,
                            f"дом {row.house}" if row.house else None,
                        )
                        if part
                    )
                ),
            )
            for row in self.addresses
        ]
        self._address_search_keys = tuple(key for _row, key in self._address_search_items)
        self._address_search_fields = tuple(
            (
                normalize_search_text(row.city),
                normalize_search_text(row.district),
                normalize_search_text(row.street),
                normalize_house(row.house) or "",
                normalize_search_text(
                    " ".join(part for part in (row.city, row.district, row.street) if part)
                ),
            )
            for row in self.addresses
        )
        street_indexes: dict[str, list[int]] = defaultdict(list)
        district_indexes: dict[str, list[int]] = defaultdict(list)
        for index, (_city_n, district_n, street_n, _house_n, _combined_n) in enumerate(
            self._address_search_fields
        ):
            if street_n:
                street_indexes[street_n].append(index)
            if district_n:
                district_indexes[district_n].append(index)
        self._address_indexes_by_street = dict(street_indexes)
        self._address_indexes_by_district = dict(district_indexes)
        self._address_street_choices = tuple(self._address_indexes_by_street)
        self._address_district_choices = tuple(self._address_indexes_by_district)
        self._address_token_buckets: dict[str, list[int]] = defaultdict(list)
        self._geo_grid: dict[tuple[int, int], list[CatalogAddress]] = defaultdict(list)

        cities: dict[str, str] = {}
        cities_by_postal: dict[str, dict[str, str]] = defaultdict(dict)
        districts: dict[str, dict[str, str]] = defaultdict(dict)
        districts_by_postal: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
        streets: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
        streets_by_postal: dict[tuple[str, str, str], dict[str, str]] = defaultdict(dict)
        houses: dict[tuple[str, str, str], dict[str, CatalogAddress]] = defaultdict(dict)
        houses_by_postal: dict[tuple[str, str, str, str], dict[str, CatalogAddress]] = defaultdict(
            dict
        )
        postal_streets: dict[str, dict[str, str]] = defaultdict(dict)
        postal_houses: dict[tuple[str, str], dict[int, CatalogAddress]] = defaultdict(dict)

        for index, (row, search_key) in enumerate(self._address_search_items):
            city_n = normalize_ui_text(row.city)
            district_n = normalize_ui_text(row.district)
            street_n = normalize_ui_text(row.street)
            house_n = normalize_ui_text(row.house)

            if city_n:
                cities.setdefault(city_n, row.city)
                if row.postal_code:
                    cities_by_postal[row.postal_code].setdefault(city_n, row.city)

            if city_n and district_n and row.district:
                districts[city_n].setdefault(district_n, row.district)
                if row.postal_code:
                    districts_by_postal[(city_n, row.postal_code)].setdefault(
                        district_n, row.district
                    )

            if city_n and district_n and street_n and row.district:
                streets[(city_n, district_n)].setdefault(street_n, row.street)
                houses[(city_n, district_n, street_n)].setdefault(house_n, row)
                if row.postal_code:
                    streets_by_postal[(city_n, district_n, row.postal_code)].setdefault(
                        street_n, row.street
                    )
                    houses_by_postal[(city_n, district_n, street_n, row.postal_code)].setdefault(
                        house_n, row
                    )

            if row.postal_code and street_n:
                postal_streets[row.postal_code].setdefault(street_n, row.street)
                postal_houses[(row.postal_code, street_n)][row.id] = row

            prefixes = {token[:3] for token in search_key.split() if len(token) >= 3}
            for prefix in prefixes:
                self._address_token_buckets[prefix].append(index)

            # ~1 км по широте; ближайший поиск затем считает точное расстояние.
            cell = (math.floor(row.latitude * 100), math.floor(row.longitude * 100))
            self._geo_grid[cell].append(row)

        self._ui_cities = self._sorted_values(cities)
        self._ui_cities_by_postal = {
            postal: self._sorted_values(values) for postal, values in cities_by_postal.items()
        }
        self._ui_districts = {
            city_n: self._sorted_values(values) for city_n, values in districts.items()
        }
        self._ui_districts_by_postal = {
            key: self._sorted_values(values) for key, values in districts_by_postal.items()
        }
        self._ui_streets = {key: self._sorted_values(values) for key, values in streets.items()}
        self._ui_streets_by_postal = {
            key: self._sorted_values(values) for key, values in streets_by_postal.items()
        }
        self._ui_houses = {
            key: self._sorted_houses(values.values()) for key, values in houses.items()
        }
        self._ui_houses_by_postal = {
            key: self._sorted_houses(values.values()) for key, values in houses_by_postal.items()
        }
        self._ui_postal_streets = {
            postal: self._sorted_values(values) for postal, values in postal_streets.items()
        }
        self._ui_postal_houses = {
            key: self._sorted_houses(values.values()) for key, values in postal_houses.items()
        }
        self._by_key: dict[str, list[StreetEntry]] = defaultdict(list)
        self._fuzzy_choices: list[str] = []
        self._fuzzy_entry_for_choice: dict[str, StreetEntry] = {}
        for entry in entries:
            for key in entry.keys:
                self._by_key[key].append(entry)
            # Для fuzzy — stem без типа/ординала как основной выбор
            primary = max(entry.keys, key=len) if entry.keys else entry.canonical
            stem_keys = sorted(
                (k for k in entry.keys if " " not in k or all(len(p) >= 3 for p in k.split())),
                key=len,
                reverse=True,
            )
            choice = stem_keys[0] if stem_keys else primary
            # Уникальный choice на entry (иначе process вернёт один ключ на несколько улиц)
            label = f"{choice}::{entry.canonical}"
            self._fuzzy_choices.append(label)
            self._fuzzy_entry_for_choice[label] = entry

    @staticmethod
    def _sorted_values(values: dict[str, str]) -> list[str]:
        return sorted(values.values(), key=normalize_ui_text)

    @staticmethod
    def _sorted_houses(values) -> list[CatalogAddress]:
        def house_key(item: CatalogAddress) -> tuple[object, ...]:
            parts = re.split(r"(\d+)", normalize_ui_text(item.house))
            return tuple(int(part) if part.isdigit() else part for part in parts)

        return sorted(values, key=lambda item: (house_key(item), item.id))

    @classmethod
    def load(cls, session: Session, *, city: str | None = "Москва") -> StreetCatalog:
        """Один SQL snapshot: старый street lookup + полный каталог домов для UI."""
        by_street: dict[tuple[str, str], StreetEntry] = {}
        addresses: list[CatalogAddress] = []
        rows = session.scalars(select(AddressRow)).yield_per(2000)
        count = 0
        for row in rows:
            count += 1
            if row.id is None:
                continue
            parsed = parse_address_text(row.address_text)
            city_name = clean_city_label(row.city) or clean_city_label(parsed.city)
            district = clean_district_label(row.district or parsed.district, city=city_name)
            raw_street = row.street or parsed.street
            house = row.house or parsed.house
            street = clean_street_house_suffix(raw_street, house)
            if not city_name or not street:
                continue
            if city is not None and city_name.strip().casefold() != city.casefold():
                continue

            street_norm = normalize_address(street)
            key = (city_name.strip(), street_norm)
            entry = by_street.get(key)
            if entry is None:
                entry = StreetEntry(
                    city=city_name.strip(),
                    canonical=street.strip(),
                    pin_id=row.id,
                    keys=street_alias_keys(street),
                )
                by_street[key] = entry
            else:
                entry.pin_id = min(entry.pin_id, row.id)

            for hk in house_lookup_keys(house):
                entry.houses.setdefault(hk, row.id)

            # Приватные адреса нужны parser street lookup как раньше, но не UI onboarding.
            if row.is_private is not True and house:
                addresses.append(
                    CatalogAddress(
                        id=row.id,
                        address_text=(
                            row.address_text.replace(raw_street, street, 1)
                            if raw_street and street != raw_street
                            else row.address_text
                        ),
                        postal_code=row.postal_code,
                        city=city_name.strip(),
                        district=district.strip() if district else None,
                        street=street.strip(),
                        house=house.strip(),
                        latitude=float(row.latitude),
                        longitude=float(row.longitude),
                    )
                )

        catalog = cls(list(by_street.values()), addresses=addresses)
        logger.info(
            "StreetCatalog загружен: addresses=%d streets=%d keys=%d",
            count,
            len(catalog.entries),
            len(catalog._by_key),
        )
        return catalog

    def get(self, address_id: int) -> CatalogAddress | None:
        return self._address_by_id.get(address_id)

    def _filtered_addresses(
        self,
        *,
        city: str | None = None,
        district: str | None = None,
        street: str | None = None,
        postal_code: str | None = None,
    ) -> list[CatalogAddress]:
        city_n = normalize_ui_text(city)
        district_n = normalize_ui_text(district)
        street_n = normalize_ui_text(street)
        return [
            row
            for row in self.addresses
            if (not city_n or normalize_ui_text(row.city) == city_n)
            and (district is None or normalize_ui_text(row.district or "") == district_n)
            and (not street_n or normalize_ui_text(row.street) == street_n)
            and (not postal_code or row.postal_code == postal_code)
        ]

    @staticmethod
    def _unique_ui(values: list[str]) -> list[str]:
        by_norm: dict[str, str] = {}
        for value in values:
            norm = normalize_ui_text(value)
            if norm:
                by_norm.setdefault(norm, value.strip())
        return sorted(by_norm.values(), key=normalize_ui_text)

    def cities(self, *, postal_code: str | None = None) -> list[str]:
        if postal_code:
            return list(self._ui_cities_by_postal.get(postal_code, ()))
        return list(self._ui_cities)

    def districts(self, city: str, *, postal_code: str | None = None) -> list[str]:
        """Только реальные районы: служебной кнопки «Район не указан» в picker быть не должно."""
        city_n = normalize_ui_text(city)
        if postal_code:
            return list(self._ui_districts_by_postal.get((city_n, postal_code), ()))
        return list(self._ui_districts.get(city_n, ()))

    def streets(
        self,
        city: str,
        district: str,
        *,
        postal_code: str | None = None,
    ) -> list[str]:
        city_n = normalize_ui_text(city)
        district_n = normalize_ui_text(district)
        if postal_code:
            return list(self._ui_streets_by_postal.get((city_n, district_n, postal_code), ()))
        return list(self._ui_streets.get((city_n, district_n), ()))

    def houses(
        self,
        city: str,
        district: str,
        street: str,
        *,
        postal_code: str | None = None,
    ) -> list[CatalogAddress]:
        key = (normalize_ui_text(city), normalize_ui_text(district), normalize_ui_text(street))
        if postal_code:
            return list(self._ui_houses_by_postal.get((*key, postal_code), ()))
        return list(self._ui_houses.get(key, ()))

    def postal_streets(self, postal_code: str) -> list[str]:
        """Улицы внутри индекса: индекс уже заменяет шаги города/района."""
        return list(self._ui_postal_streets.get(postal_code, ()))

    def postal_houses(self, postal_code: str, street: str) -> list[CatalogAddress]:
        """Дома на улице внутри индекса, без отдельного выбора города/района."""
        return list(self._ui_postal_houses.get((postal_code, normalize_ui_text(street)), ()))

    @staticmethod
    def _token_similarity(query_token: str, candidate_token: str) -> float:
        if query_token == candidate_token:
            return 100.0
        if query_token.isdigit() or candidate_token.isdigit():
            return 0.0
        if len(query_token) >= 2 and candidate_token.startswith(query_token):
            return 97.0
        if len(candidate_token) >= 4 and query_token.startswith(candidate_token):
            return 91.0
        if min(len(query_token), len(candidate_token)) < 3:
            return 0.0
        ratio = float(fuzz.ratio(query_token, candidate_token))
        partial = float(fuzz.partial_ratio(query_token, candidate_token)) * 0.92
        return max(ratio, partial)

    @classmethod
    def _text_search_score(
        cls,
        query: str,
        *,
        city: str,
        district: str,
        street: str,
        combined: str,
    ) -> float | None:
        """Field-aware scorer: улица важнее района, порядок слов не важен."""
        query_tokens = _meaningful_search_tokens(query)
        if not query_tokens:
            return 100.0

        fields = (
            (street, 3.0),
            (district, 1.5),
            (city, 0.0),
        )
        field_tokens = [
            (token, bonus)
            for value, bonus in fields
            for token in _meaningful_search_tokens(value)
            if token
        ]
        if not field_tokens:
            return None

        token_scores: list[float] = []
        for query_token in query_tokens:
            best = max(
                (
                    min(100.0, cls._token_similarity(query_token, token) + bonus)
                    for token, bonus in field_tokens
                ),
                default=0.0,
            )
            token_scores.append(best)

        coverage = sum(token_scores) / len(token_scores)
        phrase = max(
            float(fuzz.WRatio(query, combined)),
            float(fuzz.token_set_ratio(query, combined)),
        )
        street_focus = max(
            float(fuzz.WRatio(query, street)),
            float(fuzz.token_set_ratio(query, street)),
        )
        score = coverage * 0.58 + phrase * 0.27 + street_focus * 0.15

        # Один случайный общий фрагмент не должен вытягивать нерелевантный адрес.
        if score < 55.0 or (len(token_scores) > 1 and coverage < 52.0):
            return None
        return min(100.0, score)

    @staticmethod
    def _house_search_score(query_house: str, candidate_house: str) -> float:
        query_n = normalize_house_search(query_house) or ""
        candidate_n = normalize_house_search(candidate_house) or ""
        if not query_n or not candidate_n:
            return 0.0
        if query_n == candidate_n:
            return 100.0

        # Если пользователь указал корпус/строение, не подменяем его другим.
        if re.search(r"[кс]", query_n):
            return 0.0

        # house_lookup_keys уже знает, что «15к1» имеет базовый ключ «15».
        # Это надёжнее общего regex: буква «к» здесь означает корпус, а не литеру дома.
        candidate_keys = set(house_lookup_keys(candidate_house))
        if query_n in candidate_keys:
            return 88.0
        return 0.0

    def _candidate_address_indexes(
        self, query: str, *, parts: _SearchQueryParts, limit: int
    ) -> set[int]:
        """Широкий recall без полного fuzzy-scan всех 125k домов."""
        result: set[int] = set()
        query_tokens = _meaningful_search_tokens(query)

        # Быстрый exact/prefix слой. Не выбираем один bucket, как раньше: это
        # теряло хорошие адреса, если один токен был точным, а другой — с опечаткой.
        buckets = sorted(
            (
                self._address_token_buckets[token[:3]]
                for token in query_tokens
                if len(token) >= 3 and self._address_token_buckets.get(token[:3])
            ),
            key=len,
        )
        for bucket in buckets:
            if len(bucket) > 5000:
                continue
            result.update(bucket)
            if len(result) >= 5000:
                break

        # Fuzzy retrieval делаем по ~4.5k уникальных улиц, а не по каждому дому.
        # После этого разворачиваем лучшие улицы обратно в address indexes.
        street_queries = {parts.full_text, parts.text_without_house}
        street_queries.discard("")
        street_limit = max(24, limit * 2)
        for street_query in street_queries:
            for scorer in (fuzz.WRatio, fuzz.token_set_ratio):
                hits = process.extract(
                    street_query,
                    self._address_street_choices,
                    scorer=scorer,
                    score_cutoff=35,
                    limit=street_limit,
                )
                for choice, _score, _index in hits:
                    result.update(self._address_indexes_by_street.get(choice, ()))
                    if len(result) >= 6500:
                        break
                if len(result) >= 6500:
                    break
            if len(result) >= 6500:
                break

        # Если улица ещё не читается (например, пользователь набрал только район),
        # добавляем несколько похожих районов. Это маленький справочник (~сотни строк).
        if len(result) < 120 and parts.full_text:
            district_hits = process.extract(
                parts.full_text,
                self._address_district_choices,
                scorer=fuzz.WRatio,
                score_cutoff=55,
                limit=4,
            )
            for choice, _score, _index in district_hits:
                indexes = self._address_indexes_by_district.get(choice, ())
                result.update(indexes[: max(300, limit * 30)])

        return result

    def _address_search_score(self, index: int, parts: _SearchQueryParts) -> float | None:
        row = self._address_search_items[index][0]
        city, district, street, _house, combined = self._address_search_fields[index]

        # Вариант A: всё, включая число, является частью названия. Это важно для
        # «улица 1905 года» и других числовых названий.
        full_score = self._text_search_score(
            parts.full_text,
            city=city,
            district=district,
            street=street,
            combined=combined,
        )

        if not parts.house:
            return full_score

        house_score = self._house_search_score(parts.house, row.house)
        text_without_house = self._text_search_score(
            parts.text_without_house,
            city=city,
            district=district,
            street=street,
            combined=combined,
        )

        # Явные «дом/корпус/строение» считаем строгими: неверный номер не должен
        # появляться выше правильного адреса из-за похожей улицы.
        if parts.explicit_house:
            if house_score <= 0.0 or text_without_house is None:
                return None
            return min(100.0, text_without_house * 0.72 + house_score * 0.28 + 1.5)

        # Голое число двусмысленно. «15 сельск» — почти наверняка дом 15,
        # но «1905 года» — часть названия улицы. Если число не встречается в
        # названии улицы и не совпало с домом, такой кандидат отбрасываем.
        street_tokens = set(_meaningful_search_tokens(street))
        number_is_in_street = (normalize_house(parts.house) or parts.house) in street_tokens
        if house_score <= 0.0 and not number_is_in_street:
            return None

        house_interpretation: float | None = None
        if house_score > 0.0 and text_without_house is not None:
            house_interpretation = min(100.0, text_without_house * 0.72 + house_score * 0.28 + 1.0)
        candidates = [score for score in (full_score, house_interpretation) if score is not None]
        return max(candidates) if candidates else None

    def search(self, query: str, *, limit: int = 12) -> list[tuple[CatalogAddress, float]]:
        query_n = normalize_search_text(query)
        if len(query_n) < 3 or not self._address_search_items:
            return []

        parts = _search_query_parts(query_n)
        candidate_indexes = self._candidate_address_indexes(query_n, parts=parts, limit=limit)

        ranked: list[tuple[float, CatalogAddress]] = []
        for index in candidate_indexes:
            score = self._address_search_score(index, parts)
            if score is None or score < 58.0:
                continue
            ranked.append((score, self._address_search_items[index][0]))

        ranked.sort(
            key=lambda pair: (-pair[0], normalize_search_text(pair[1].address_text), pair[1].id)
        )
        return [(row, score) for score, row in ranked[:limit]]

    def nearest(
        self,
        latitude: float,
        longitude: float,
        *,
        limit: int = 5,
        max_distance_m: float = 1500.0,
    ) -> list[CatalogAddress]:
        """Ближайшие дома к курсору, но не случайный дом в другом районе/городе."""
        lat_scale = math.cos(math.radians(latitude))

        def distance_sq(row: CatalogAddress) -> float:
            dy = (row.latitude - latitude) * 111_320.0
            dx = (row.longitude - longitude) * 111_320.0 * lat_scale
            return dx * dx + dy * dy

        max_sq = max_distance_m * max_distance_m
        lat_step = max(1, math.ceil(max_distance_m / 111_320.0 * 100))
        lon_denominator = max(1.0, 111_320.0 * max(abs(lat_scale), 0.1))
        lon_step = max(1, math.ceil(max_distance_m / lon_denominator * 100))
        center_lat = math.floor(latitude * 100)
        center_lon = math.floor(longitude * 100)
        rows: list[CatalogAddress] = []
        for lat_cell in range(center_lat - lat_step, center_lat + lat_step + 1):
            for lon_cell in range(center_lon - lon_step, center_lon + lon_step + 1):
                rows.extend(self._geo_grid.get((lat_cell, lon_cell), ()))

        candidates: list[tuple[float, CatalogAddress]] = []
        for row in rows:
            distance = distance_sq(row)
            if distance <= max_sq:
                candidates.append((distance, row))
        return [
            row
            for _distance, row in heapq.nsmallest(
                limit,
                candidates,
                key=lambda item: item[0],
            )
        ]

    def lookup(self, hint: str, *, house: str | None = None) -> StreetHit | None:
        if not hint or not hint.strip():
            return None
        entry = self._resolve_entry(hint)
        if entry is None:
            return None
        address_id = entry.pin_id
        matched_house: str | None = None
        for hk in house_lookup_keys(house):
            if hk in entry.houses:
                address_id = entry.houses[hk]
                matched_house = hk
                break
        return StreetHit(
            city=entry.city,
            canonical=entry.canonical,
            pin_id=entry.pin_id,
            address_id=address_id,
            score=100.0,
            house=matched_house,
        )

    def lookup_hints(self, hints: list[str], *, house: str | None = None) -> StreetHit | None:
        from parser_common.geo_text import filter_moscow_location_hints, is_bare_other_city_hint

        hints = filter_moscow_location_hints(hints)
        best: StreetHit | None = None
        for hint in hints:
            if is_bare_other_city_hint(hint):
                continue
            hit = self.lookup(hint, house=house)
            if hit is None:
                continue
            if (
                best is None
                or hit.score > best.score
                or (hit.score == best.score and hit.house and not best.house)
            ):
                best = hit
        return best

    def lookup_all_hints(
        self,
        hints: list[str],
        *,
        house: str | None = None,
    ) -> list[StreetHit]:
        """Все уникальные улицы из hints (для fan-out ЖЭК-объявлений по улицам)."""
        from parser_common.geo_text import filter_moscow_location_hints, is_bare_other_city_hint

        hints = filter_moscow_location_hints(hints)
        by_pin: dict[int, StreetHit] = {}
        for hint in hints:
            if is_bare_other_city_hint(hint):
                continue
            hit = self.lookup(hint, house=house)
            if hit is None:
                continue
            prev = by_pin.get(hit.pin_id)
            if prev is None or (hit.house and not prev.house) or hit.score > prev.score:
                by_pin[hit.pin_id] = hit
        return list(by_pin.values())

    def _resolve_entry(self, hint: str) -> StreetEntry | None:
        keys = hint_keys(hint)
        # 1) exact
        exact_hits: list[StreetEntry] = []
        seen: set[int] = set()
        for key in keys:
            for entry in self._by_key.get(key, ()):
                if id(entry) not in seen:
                    seen.add(id(entry))
                    exact_hits.append(entry)
        if len(exact_hits) == 1:
            return exact_hits[0]
        if len(exact_hits) > 1:
            # Несколько exact — берём с наибольшим пересечением ключей
            scored = sorted(
                exact_hits,
                key=lambda e: len(e.keys & keys),
                reverse=True,
            )
            if len(scored) == 1 or len(scored[0].keys & keys) > len(scored[1].keys & keys):
                return scored[0]
            return None  # неоднозначно

        # 2) contains / prefix (длина ключа ≥ 4)
        contain_hits: list[tuple[int, StreetEntry]] = []
        for key in keys:
            if len(key) < 4:
                continue
            for indexed, entries in self._by_key.items():
                if len(indexed) < 4:
                    continue
                if key == indexed:
                    continue
                if key in indexed or indexed in key:
                    for entry in entries:
                        contain_hits.append((min(len(key), len(indexed)), entry))
        if contain_hits:
            contain_hits.sort(key=lambda pair: pair[0], reverse=True)
            top_len = contain_hits[0][0]
            top_entries = []
            seen_c: set[int] = set()
            for length, entry in contain_hits:
                if length < top_len:
                    break
                if id(entry) not in seen_c:
                    seen_c.add(id(entry))
                    top_entries.append(entry)
            if len(top_entries) == 1:
                return top_entries[0]
            if len(top_entries) > 1:
                return None

        # 3) fuzzy
        return self._fuzzy_lookup(keys)

    def _fuzzy_lookup(self, keys: set[str]) -> StreetEntry | None:
        if not self._fuzzy_choices:
            return None
        query = max(keys, key=len) if keys else ""
        if len(query) < 4:
            return None

        # Сравниваем с частью до ::
        def _scorer(q: str, choice: str, **kwargs: object) -> float:
            label = choice.split("::", 1)[0]
            return float(fuzz.WRatio(q, label, **kwargs))

        results = process.extract(
            query,
            self._fuzzy_choices,
            scorer=_scorer,
            limit=3,
        )
        if not results:
            return None
        best_label, best_score, _ = results[0]
        if best_score < self.fuzzy_threshold:
            return None
        if len(results) > 1 and best_score - results[1][1] < self.fuzzy_margin:
            return None
        return self._fuzzy_entry_for_choice.get(best_label)
