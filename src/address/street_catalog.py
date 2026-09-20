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

from address.components import clean_city_label, clean_district_label, parse_address_text
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
    """Поисковый ключ без пунктуации: удобно для живых подсказок по частичному адресу."""
    normalized = normalize_ui_text(value)
    return " ".join(_SEARCH_SEPARATOR_RE.sub(" ", normalized).split())


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
                        part for part in (row.city, row.district, row.street, row.house) if part
                    )
                ),
            )
            for row in self.addresses
        ]
        self._address_search_keys = tuple(key for _row, key in self._address_search_items)
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
            street = row.street or parsed.street
            house = row.house or parsed.house
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
                        address_text=row.address_text,
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
    def _autocomplete_score(query: str, address: str) -> float | None:
        """Оценка частичного адреса без требования вводить строку целиком."""
        if address.startswith(query):
            return 100.0
        position = address.find(query)
        if position >= 0:
            return max(90.0, 98.0 - position * 0.15)

        query_tokens = query.split()
        address_tokens = address.split()
        if not query_tokens:
            return None

        cursor = 0
        positions: list[int] = []
        exact = 0
        for query_token in query_tokens:
            found = None
            for index in range(cursor, len(address_tokens)):
                token = address_tokens[index]
                if token.startswith(query_token):
                    found = index
                    exact += int(token == query_token)
                    break
            if found is None:
                return None
            positions.append(found)
            cursor = found + 1

        span = positions[-1] - positions[0] + 1
        gaps = max(0, span - len(positions))
        score = 88.0 - positions[0] * 0.35 - gaps * 0.8 + exact * 0.5
        return max(72.0, min(96.0, score))

    def search(self, query: str, *, limit: int = 12) -> list[tuple[CatalogAddress, float]]:
        query_n = normalize_search_text(query)
        if len(query_n) < 3 or not self._address_search_items:
            return []

        seed = next((token[:3] for token in query_n.split() if len(token) >= 3), None)
        candidate_indexes = (
            self._address_token_buckets.get(seed, [])
            if seed
            else range(len(self._address_search_items))
        )

        ranked: list[tuple[float, CatalogAddress]] = []
        for index in candidate_indexes:
            row, address_key = self._address_search_items[index]
            score = self._autocomplete_score(query_n, address_key)
            if score is not None:
                ranked.append((score, row))

        if ranked:
            ranked.sort(
                key=lambda pair: (-pair[0], normalize_search_text(pair[1].address_text), pair[1].id)
            )
            return [(row, score) for score, row in ranked[:limit]]

        # Опечатки оставляем как fallback, но только когда prefix/contains ничего не нашли.
        hits = process.extract(
            query_n,
            self._address_search_keys,
            scorer=fuzz.WRatio,
            limit=max(limit * 3, 20),
        )
        result: list[tuple[CatalogAddress, float]] = []
        seen: set[int] = set()
        for _choice, score, index in hits:
            row = self._address_search_items[index][0]
            if row.id in seen or score < 60:
                continue
            seen.add(row.id)
            result.append((row, float(score)))
            if len(result) >= limit:
                break
        return result

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
