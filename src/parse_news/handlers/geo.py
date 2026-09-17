"""Геопривязка новости: индекс или улица из московского справочника."""

from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from address.db.address import AddressRow
from address.db.queries import load_addresses_by_postcodes
from address.geocoding import GeoMatcher, normalize_address
from address.models.address import Address
from parse_news.models.article import RawNewsArticle
from project.logging_setup import get_logger

logger = get_logger(__name__)

_POSTCODE = re.compile(r"(?<!\w)[0-9]{6}(?!\w)")

# «ул. Тверская», «на улице Арбат», «Ленинский проспект»
# Важно: type-after только с ОДНИМ словом имени, иначе «Авария на улице …»
# съедает «улице» и ломает поиск имени после типа.
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
            address = Address(
                id=row.id,
                postal_code=row.postal_code,
                address_text=row.address_text,
                latitude=row.latitude,
                longitude=row.longitude,
                is_private=row.is_private,
            )
            street_key = _street_key_from_address_text(address.address_text)
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
            # Частичное совпадение: «тверская» ⊂ ключей
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


def _street_key_from_address_text(address_text: str) -> str | None:
    """«Москва, улица Тверская, д. 1» → «тверская»."""
    normalized = normalize_address(address_text)
    parts = [p.strip() for p in address_text.split(",") if p.strip()]
    for part in reversed(parts):
        part_norm = normalize_address(part)
        if any(
            t in part_norm.split()
            for t in (
                "улица",
                "проспект",
                "проезд",
                "переулок",
                "шоссе",
                "бульвар",
                "набережная",
                "площадь",
                "аллея",
            )
        ):
            words = [
                w
                for w in part_norm.split()
                if w
                not in {
                    "улица",
                    "проспект",
                    "проезд",
                    "переулок",
                    "шоссе",
                    "бульвар",
                    "набережная",
                    "площадь",
                    "аллея",
                    "москва",
                }
            ]
            key = " ".join(words)
            return key or None
    # fallback: всё кроме города/дома
    words = [
        w
        for w in normalized.split()
        if w not in {"москва", "дом", "корпус", "строение"} and not w.isdigit()
    ]
    return " ".join(words[:4]) or None


def extract_postcodes(text: str) -> list[str]:
    return list(dict.fromkeys(_POSTCODE.findall(text)))


def extract_street_hints(text: str) -> list[str]:
    hints: list[str] = []
    for match in _STREET_HINT.finditer(text):
        raw = match.group("name1") or match.group("name2") or ""
        # Обрезаем хвост после запятой / «дом»
        raw = re.split(r"[,;]|\bдом\b|\bд\.", raw, maxsplit=1)[0]
        cleaned = " ".join(
            w for w in re.findall(r"[А-ЯЁа-яё0-9\-]+", raw) if w.lower() not in _STOP_WORDS
        )
        if len(cleaned) < 3:
            continue
        # Отбрасываем явный мусор (глаголы/общие слова без заглавной середины уже отфильтрованы)
        if cleaned.lower() in _STOP_WORDS:
            continue
        hints.append(cleaned)
    return list(dict.fromkeys(hints))


def resolve_article_address(
    session: Session,
    article: RawNewsArticle,
    *,
    street_index: MoscowStreetIndex | None = None,
) -> int | None:
    """
    address_id только при явном месте в тексте:
      1) почтовый индекс → GeoMatcher по домам индекса;
      2) упоминание улицы → кандидаты из street_index / БД → GeoMatcher.
    Иначе None (без дефолтной Москвы).
    """
    parts = [article.title, article.body or ""]
    text = "\n".join(part for part in parts if part)
    if not text.strip():
        return None

    postcodes = extract_postcodes(text)
    if postcodes:
        addresses = load_addresses_by_postcodes(session, postcodes)
        address_id = _match_address(text, addresses)
        if address_id is not None:
            return address_id

    hints = extract_street_hints(text)
    if not hints:
        return None

    if street_index is not None:
        candidates = street_index.candidates_for_hints(hints)
    else:
        candidates = _load_candidates_by_sql(session, hints)

    return _match_address(text, candidates)


def _match_address(text: str, addresses: list[Address]) -> int | None:
    if not addresses:
        return None
    # Ограничиваем размер для RapidFuzz
    if len(addresses) > 800:
        addresses = addresses[:800]
    matcher = GeoMatcher(addresses)
    geo = matcher.resolve(text)
    if geo.method == "fallback" or geo.address_id is None:
        return None
    return geo.address_id


def _load_candidates_by_sql(session: Session, hints: list[str]) -> list[Address]:
    """Fallback без индекса: ILIKE по кускам улицы (дорого, только если индекс не загружен)."""
    from sqlalchemy import or_

    clauses = []
    for hint in hints[:5]:
        token = hint.strip()
        if len(token) < 3:
            continue
        clauses.append(AddressRow.address_text.ilike(f"%{token}%"))
    if not clauses:
        return []
    rows = session.scalars(select(AddressRow).where(or_(*clauses)).limit(400)).all()
    return [
        Address(
            id=row.id,
            postal_code=row.postal_code,
            address_text=row.address_text,
            latitude=row.latitude,
            longitude=row.longitude,
            is_private=row.is_private,
        )
        for row in rows
    ]
