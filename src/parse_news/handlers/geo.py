"""Геопривязка новости: только Москва / улицы справочника; чужие регионы → null."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from address.db.queries import load_addresses_by_postcodes
from address.geocoding import GeoMatcher
from address.models.address import Address
from address.resolve import OUTLET_DEFAULT_CITY, GeoBind, GeoByLevel, find_geo_bind
from address.street_catalog import StreetCatalog
from parse_news.models.article import RawNewsArticle
from project.logging_setup import get_logger

logger = get_logger(__name__)

MoscowStreetIndex = StreetCatalog

_POSTCODE = re.compile(r"(?<!\w)[0-9]{6}(?!\w)")
_HOUSE_IN_TEXT = re.compile(
    r"(?:д\.?|дом)\s*(?P<house>[0-9]+[а-яА-Яa-zA-Z]?(?:\s*[кс]\s*[0-9]+[а-яА-Яa-zA-Z]?)?)",
    re.IGNORECASE,
)
_CITY_MOSCOW = re.compile(
    r"\bмоскв[аеуы]\b|\bв\s+столиц[еу]\b|\bподмосков",
    re.IGNORECASE,
)

# Иностранные государства / области / города. Всегда out-of-scope
# (даже если в тексте есть «Москва» как политический актор).
_FOREIGN_GEO = re.compile(
    r"(?i)\b(?:"
    r"украин|киев|харьков|одесс|запорож|херсон|львов|"
    r"днепропетровск|днепродзержинск|днепр|"
    r"крив(?:ой|ом|ого)?\s+рог|"
    r"полтав|сум[ыах]|чернигов|винниц|житомир|хмельниц|"
    r"ровенск|луцк|ивано[-\s]?франков|тернопол|черкас|черновц|"
    r"николаевск|мариупол|мелитопол|бердянск|краматорск|"
    r"словянск|бахмут|авдеевк|покровск|купянск|"
    r"донбасс|донецк|луганск|новоросси|крым|севастопол|"
    r"лнр|днр|"
    r"беларус|белорусс|минск|гомел|брест|гродн|витебск|могил[её]в|"
    r"казахстан|алмат|астан[аы]|нур[-\s]?султан|"
    r"узбекистан|ташкент|киргиз|бишкек|таджикистан|душанбе|"
    r"туркменистан|ашхабад|молдав|кишин[её]в|"
    r"грузи|тбилиси|армени|ереван|азербайдж|баку|"
    r"китай|пекин|\bсша\b|америк|вашингтон|"
    r"евросоюз|\bес\b|израил|сири|турци|"
    r"польш|герман|франци|британ|нато|иран|ирак|афганистан|"
    r"япони|коре[яй]|инди[яи]|пакистан|египет|ливи|"
    r"зарубеж|за\s+рубеж"
    r")\w*",
)

# Другие субъекты РФ — не вешаем Москву (если нет явного московского контекста).
_OTHER_RU_GEO = re.compile(
    r"(?i)\b(?:"
    r"петербург|санкт[-\s]?петербург|\bспб\b|ленинград|"
    r"новосибирск|екатеринбург|казан|челябинск|самар|"
    r"нижегород|нижн\w+\s+новгород|ростов[-\s]?на[-\s]?дону|"
    r"краснодар|воронеж|пермь|волгоград|красноярск|уф[аые]|"
    r"владивосток|хабаровск|иркутск|тюмен|омск|томск|"
    r"саратов|тольятти|ижевск|барнаул|ульяновск|"
    r"ярославл|владикавказ|махачкал|грозн|"
    r"калининград|мурманск|архангельск|сочи"
    r")\w*",
)

_NAKED_STREET = re.compile(
    r"(?:^|[\s,.;:(])(?:на|по|у)\s+(?P<name>[А-ЯЁ][а-яё]{3,20})(?:\s|,|\.|$)",
)

_TYPE = (
    r"(?:ул\.?|улиц[аеыу]|пр-?т\.?|проспект[аеу]?|пер\.?|переул(?:ок|ке|ка)|"
    r"ш\.?|шоссе|б-?р\.?|бульвар[аеу]?|наб\.?|набережн(?:ая|ой|ую)|"
    r"пл\.?|площад[ьи]|проезд[аеу]?|алле[яию])"
)

_STREET_HINT = re.compile(
    rf"(?:"
    rf"(?P<ord1>\d+-?[йяе])\s+"
    rf"(?P<name_ord>[А-ЯЁ][а-яё0-9\-]*(?:\s+[А-ЯЁ][а-яё0-9\-]*){{0,2}})\s+"
    rf"{_TYPE}"
    rf"|"
    rf"{_TYPE}\s+"
    rf"(?P<name1>(?:\d+-?[йяе]\s+)?[А-ЯЁ][а-яё0-9\-]*(?:\s+[А-ЯЁ][а-яё0-9\-]*){{0,3}})"
    rf"|"
    rf"(?P<name2>[А-ЯЁ][а-яё0-9\-]*(?:\s+[А-ЯЁ][а-яё0-9\-]*){{0,2}})\s+"
    rf"{_TYPE}"
    rf")"
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
        "сегодня",
        "вечера",
        "утра",
    }
)


def article_text(article: RawNewsArticle) -> str:
    return "\n".join(part for part in (article.title, article.body or "") if part)


def is_moscow_context(text: str) -> bool:
    return bool(_CITY_MOSCOW.search(text))


def is_foreign_geo(text: str) -> bool:
    """Иностранное государство / область / город (не ЖКХ Москвы)."""
    if not text.strip():
        return False
    return bool(_FOREIGN_GEO.search(text))


def is_non_moscow_geo(text: str) -> bool:
    """Чужой город/регион/страна — вне скоупа бота.

    Иностранный маркер всегда out-of-scope (даже если в тексте есть «Москва»
    как политический актор). Прочие города РФ — тоже, если нет явной Москвы
    как места события.
    """
    if not text.strip():
        return False
    if is_foreign_geo(text):
        return True
    if is_moscow_context(text):
        return False
    return bool(_OTHER_RU_GEO.search(text))


def should_skip_foreign_article(article: RawNewsArticle) -> bool:
    """Не создавать событие по иностранным государствам и их областям."""
    return is_foreign_geo(article_text(article))


def extract_postcodes(text: str) -> list[str]:
    return list(dict.fromkeys(_POSTCODE.findall(text)))


def extract_house(text: str) -> str | None:
    match = _HOUSE_IN_TEXT.search(text)
    if not match:
        return None
    return re.sub(r"\s+", "", match.group("house"))


def extract_street_hints(text: str) -> list[str]:
    hints: list[str] = []
    for match in _STREET_HINT.finditer(text):
        if match.group("ord1") and match.group("name_ord"):
            raw = f"{match.group('ord1')} {match.group('name_ord')}"
        else:
            raw = match.group("name1") or match.group("name2") or ""
        raw = re.split(r"[,;]|\bдом\b|\bд\.", raw, maxsplit=1)[0]
        tokens = re.findall(r"[А-ЯЁа-яё0-9\-]+", raw)
        cleaned = " ".join(w for w in tokens if w.lower() not in _STOP_WORDS)
        if len(cleaned) < 3:
            continue
        if cleaned.lower() in _STOP_WORDS:
            continue
        # Не тащим инородные топонимы в StreetCatalog (Днепропетровская ул. в Москве).
        if is_foreign_geo(cleaned):
            continue
        hints.append(cleaned)

    for match in _NAKED_STREET.finditer(text):
        name = match.group("name")
        if name.lower() in _STOP_WORDS or len(name) < 4:
            continue
        if is_foreign_geo(name):
            continue
        hints.append(name)

    return list(dict.fromkeys(hints))


def resolve_article_geo(
    session: Session,
    article: RawNewsArticle,
    *,
    street_index: StreetCatalog | None = None,
) -> GeoBind | None:
    """
    Только Москва и её улицы. Чужой город/страна → None (без дефолта Москвы).

    Каскад:
      1) geo_* источника (город должен быть Москвой);
      2) текст: индекс / StreetCatalog (локальный outlet или явная Москва) /
         явное «Москва»;
      3) дефолт Москвы — только m24/msk1/mskagency без чужой географии.
    """
    text = article_text(article)
    if is_non_moscow_geo(text):
        return None

    moscow = is_moscow_context(text)
    local_outlet = article.outlet in OUTLET_DEFAULT_CITY

    bind = _resolve_from_source_fields(
        session,
        article,
        street_index=street_index,
        allow_moscow=True,
    )
    if bind is not None:
        return bind

    bind = _resolve_from_text(
        session,
        article,
        street_index=street_index,
        text=text,
        allow_streets=local_outlet or moscow,
    )
    if bind is not None:
        return bind

    if local_outlet:
        return find_geo_bind(session, city=OUTLET_DEFAULT_CITY[article.outlet])
    return None


def resolve_article_address(
    session: Session,
    article: RawNewsArticle,
    *,
    street_index: StreetCatalog | None = None,
) -> int | None:
    bind = resolve_article_geo(session, article, street_index=street_index)
    return bind.address_id if bind else None


def _resolve_from_source_fields(
    session: Session,
    article: RawNewsArticle,
    *,
    street_index: StreetCatalog | None,
    allow_moscow: bool,
) -> GeoBind | None:
    if not (article.geo_city or article.geo_street or article.geo_house):
        return None

    city = (article.geo_city or "").strip()
    if city and not _CITY_MOSCOW.search(city):
        # Явно другой город в метаданных — не привязываем к Москве.
        return None
    if not allow_moscow and not city:
        return None

    if article.geo_street and street_index is not None and allow_moscow:
        hit = street_index.lookup(article.geo_street, house=article.geo_house)
        if hit is not None:
            geo_by = GeoByLevel.HOME if hit.house else GeoByLevel.STREET
            return GeoBind(address_id=hit.address_id, geo_by=geo_by)

    bind = find_geo_bind(
        session,
        city=city or "Москва",
        street=article.geo_street,
        house=article.geo_house,
    )
    if bind is not None and bind.geo_by != GeoByLevel.CITY:
        return bind
    if city and not article.geo_street:
        return find_geo_bind(session, city=city)
    return None


def _resolve_from_text(
    session: Session,
    article: RawNewsArticle,
    *,
    street_index: StreetCatalog | None,
    text: str,
    allow_streets: bool,
) -> GeoBind | None:
    if not text.strip():
        return None

    if allow_streets:
        postcodes = extract_postcodes(text)
        if postcodes:
            addresses = load_addresses_by_postcodes(session, postcodes)
            address_id = _match_address(text, addresses)
            if address_id is not None:
                return GeoBind(address_id=address_id, geo_by=GeoByLevel.HOME)

        hints = extract_street_hints(text)
        house = extract_house(text)
        if hints and street_index is not None:
            hit = street_index.lookup_hints(hints, house=house)
            if hit is not None:
                geo_by = GeoByLevel.HOME if (house and hit.house) else GeoByLevel.STREET
                return GeoBind(address_id=hit.address_id, geo_by=geo_by)

    if is_moscow_context(text):
        return find_geo_bind(session, city="Москва")
    return None


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
