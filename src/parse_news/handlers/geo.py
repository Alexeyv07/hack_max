"""Геопривязка новости: каскад source → text → outlet default."""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from address.components import normalize_component
from address.db.address import AddressRow
from address.db.queries import address_from_row, load_addresses_by_postcodes
from address.geocoding import GeoMatcher, normalize_address
from address.models.address import Address
from address.resolve import OUTLET_DEFAULT_CITY, GeoBind, GeoByLevel, find_geo_bind
from parse_news.models.article import RawNewsArticle
from project.logging_setup import get_logger

logger = get_logger(__name__)

_POSTCODE = re.compile(r"(?<!\w)[0-9]{6}(?!\w)")
_HOUSE_IN_TEXT = re.compile(
    r"(?:д\.?|дом)\s*(?P<house>[0-9]+[а-яА-Яa-zA-Z]?)",
    re.IGNORECASE,
)
_CITY_MOSCOW = re.compile(
    r"\bмоскв[аеуы]\b|\bв\s+столиц[еу]\b",
    re.IGNORECASE,
)

# «ул. Тверская», «на улице Арбат», «Ленинский проспект»
_STREET_HINT = re.compile(
    r"(?:"
    r"(?:ул\.?|улиц[аеыу]|пр-?т\.?|проспект[аеу]?|пер\.?|переул(?:ок|ке|ка)|"
    r"ш\.?|шоссе|б-?р\.?|бульвар[аеу]?|наб\.?|набережн(?:ая|ой|ую)|"
    r"пл\.?|площад[ьи]|проезд[аеу]?)\s+"
    r"(?P<name1>[А-ЯЁ][а-яё0-9\-]*(?:\s+[А-ЯЁа-яё0-9\-]+){0,2})"
    r"|"
    r"(?P<name2>[А-ЯЁ][а-яё0-9\-]+)\s+"
    r"(?:проспект[аеу]?|переул(?:ок|ке|ка)|шоссе|бульвар[аеу]?|"
    r"набережн(?:ая|ой)|площад[ьи]|проезд[аеу]?|пр-?т\.?)"
    r")"
)

_STOP_WORDS = frozenset(
    {
        "в",
        "на",
        "по",
        "у",
        "и",
        "или",
        "дом",
        "корпус",
        "строение",
        "д",
        "к",
        "стр",
        "года",
        "году",
        "москве",
        "москва",
        "районе",
        "район",
    }
)

_STREET_TYPE_WORDS = frozenset(
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
    }
)


class MoscowStreetIndex:
    """Снимок улиц из addresses: нормализованное имя улицы → адреса."""

    def __init__(self, by_street: dict[str, list[Address]]) -> None:
        self.by_street = by_street

    @classmethod
    def load(cls, session: Session) -> MoscowStreetIndex:
        by_street: dict[str, list[Address]] = defaultdict(list)
        rows = session.scalars(select(AddressRow)).yield_per(2000)
        count = 0
        for row in rows:
            address = address_from_row(row)
            street_key = _street_key_from_row(row)
            if street_key:
                by_street[street_key].append(address)
            count += 1
        logger.info(
            "Индекс улиц Москвы загружен: addresses=%d streets=%d",
            count,
            len(by_street),
        )
        return cls(dict(by_street))

    def candidates_for_hints(self, hints: list[str]) -> list[Address]:
        out: list[Address] = []
        seen: set[int] = set()
        for hint in hints:
            key = normalize_address(hint)
            if not key:
                continue
            for address in self.by_street.get(key, ()):
                if address.id not in seen:
                    seen.add(address.id)
                    out.append(address)
            if key not in self.by_street and len(key) >= 4:
                for street, addresses in self.by_street.items():
                    if key in street or street in key:
                        for address in addresses:
                            if address.id not in seen:
                                seen.add(address.id)
                                out.append(address)
                        if len(out) > 400:
                            break
        return out


def _street_key_from_row(row: AddressRow) -> str | None:
    if row.street:
        words = [
            w
            for w in normalize_address(row.street).split()
            if w not in _STREET_TYPE_WORDS and w != "москва"
        ]
        return " ".join(words) or None
    return _street_key_from_address_text(row.address_text)


def _street_key_from_address_text(address_text: str) -> str | None:
    """«Москва, улица Тверская, д. 1» → «тверская»."""
    normalized = normalize_address(address_text)
    parts = [p.strip() for p in address_text.split(",") if p.strip()]
    for part in reversed(parts):
        part_norm = normalize_address(part)
        if any(t in part_norm.split() for t in _STREET_TYPE_WORDS):
            words = [w for w in part_norm.split() if w not in _STREET_TYPE_WORDS | {"москва"}]
            key = " ".join(words)
            return key or None
    words = [
        w
        for w in normalized.split()
        if w not in {"москва", "дом", "корпус", "строение"} and not w.isdigit()
    ]
    return " ".join(words[:4]) or None


def extract_postcodes(text: str) -> list[str]:
    return list(dict.fromkeys(_POSTCODE.findall(text)))


def extract_house(text: str) -> str | None:
    match = _HOUSE_IN_TEXT.search(text)
    return match.group("house") if match else None


def extract_street_hints(text: str) -> list[str]:
    hints: list[str] = []
    for match in _STREET_HINT.finditer(text):
        raw = match.group("name1") or match.group("name2") or ""
        raw = re.split(r"[,;]|\bдом\b|\bд\.", raw, maxsplit=1)[0]
        cleaned = " ".join(
            w for w in re.findall(r"[А-ЯЁа-яё0-9\-]+", raw) if w.lower() not in _STOP_WORDS
        )
        if len(cleaned) < 3:
            continue
        if cleaned.lower() in _STOP_WORDS:
            continue
        hints.append(cleaned)
    return list(dict.fromkeys(hints))


def resolve_article_geo(
    session: Session,
    article: RawNewsArticle,
    *,
    street_index: MoscowStreetIndex | None = None,
) -> GeoBind | None:
    """
    Каскад геопривязки:
      1) структурированные поля источника (geo_city / geo_street / geo_house);
      2) анализ title+body (индекс → улица/дом → упоминание города);
      3) дефолт города по outlet (m24/msk1/mskagency → Москва, geo_by=city).
    """
    bind = _resolve_from_source_fields(session, article)
    if bind is not None:
        return bind

    bind = _resolve_from_text(session, article, street_index=street_index)
    if bind is not None:
        return bind

    city = OUTLET_DEFAULT_CITY.get(article.outlet)
    if city:
        return find_geo_bind(session, city=city)
    return None


def resolve_article_address(
    session: Session,
    article: RawNewsArticle,
    *,
    street_index: MoscowStreetIndex | None = None,
) -> int | None:
    """Совместимость: только address_id."""
    bind = resolve_article_geo(session, article, street_index=street_index)
    return bind.address_id if bind else None


def _resolve_from_source_fields(session: Session, article: RawNewsArticle) -> GeoBind | None:
    if not (article.geo_city or article.geo_street or article.geo_house):
        return None
    return find_geo_bind(
        session,
        city=article.geo_city,
        street=article.geo_street,
        house=article.geo_house,
    )


def _resolve_from_text(
    session: Session,
    article: RawNewsArticle,
    *,
    street_index: MoscowStreetIndex | None,
) -> GeoBind | None:
    parts = [article.title, article.body or ""]
    text = "\n".join(part for part in parts if part)
    if not text.strip():
        return None

    postcodes = extract_postcodes(text)
    if postcodes:
        addresses = load_addresses_by_postcodes(session, postcodes)
        address_id = _match_address(text, addresses)
        if address_id is not None:
            return _bind_matched(session, address_id, text, prefer_home=True)

    hints = extract_street_hints(text)
    house = extract_house(text)
    if hints:
        bind = _bind_street_components(session, hints=hints, house=house)
        if bind is not None:
            return bind

        if street_index is not None:
            candidates = street_index.candidates_for_hints(hints)
        else:
            candidates = _load_candidates_by_sql(session, hints)
        address_id = _match_address(text, candidates)
        if address_id is not None:
            return _bind_matched(session, address_id, text, prefer_home=bool(house))

    if _CITY_MOSCOW.search(text):
        return find_geo_bind(session, city="Москва")
    return None


def _bind_street_components(
    session: Session,
    *,
    hints: list[str],
    house: str | None,
) -> GeoBind | None:
    """Прямое сопоставление по city+street(+house) без fuzzy."""
    for hint in hints:
        # В справочнике street часто «улица Тверская» — пробуем несколько вариантов.
        variants = [
            hint,
            f"улица {hint}",
            f"проспект {hint}",
            f"переулок {hint}",
            f"проезд {hint}",
            f"шоссе {hint}",
            f"бульвар {hint}",
            f"набережная {hint}",
            f"площадь {hint}",
        ]
        for street in variants:
            bind = find_geo_bind(session, city="Москва", street=street, house=house)
            if bind is None:
                continue
            if bind.geo_by == GeoByLevel.CITY:
                # city-only не считаем успехом поиска улицы
                continue
            return bind
    return None


def _bind_matched(
    session: Session,
    address_id: int,
    text: str,
    *,
    prefer_home: bool,
) -> GeoBind:
    row = session.get(AddressRow, address_id)
    house = extract_house(text)
    if prefer_home or (
        house and row is not None and normalize_component(house) == normalize_component(row.house)
    ):
        return GeoBind(address_id=address_id, geo_by=GeoByLevel.HOME)
    if row is not None and row.street:
        return GeoBind(address_id=address_id, geo_by=GeoByLevel.STREET)
    return GeoBind(address_id=address_id, geo_by=GeoByLevel.CITY)


def _match_address(text: str, addresses: list[Address]) -> int | None:
    if not addresses:
        return None
    if len(addresses) > 800:
        addresses = addresses[:800]
    matcher = GeoMatcher(addresses)
    geo = matcher.resolve(text)
    if geo.method == "fallback" or geo.address_id is None:
        return None
    return geo.address_id


def _load_candidates_by_sql(session: Session, hints: list[str]) -> list[Address]:
    clauses = []
    for hint in hints[:5]:
        token = hint.strip()
        if len(token) < 3:
            continue
        clauses.append(AddressRow.street.ilike(f"%{token}%"))
        clauses.append(AddressRow.address_text.ilike(f"%{token}%"))
    if not clauses:
        return []
    rows = session.scalars(select(AddressRow).where(or_(*clauses)).limit(400)).all()
    return [address_from_row(row) for row in rows]
