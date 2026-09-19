"""Текстовые эвристики гео: Москва / улицы / иностранные маркеры.

Общий слой для parse_news / parse_mc (без доменных Raw* и без SQL).
"""

from __future__ import annotations

import re

_POSTCODE = re.compile(r"(?<!\w)[0-9]{6}(?!\w)")
_HOUSE_IN_TEXT = re.compile(
    r"(?:д\.?|дом)\s*(?P<house>[0-9]+[а-яА-Яa-zA-Z]?(?:\s*[кс]\s*[0-9]+[а-яА-Яa-zA-Z]?)?)",
    re.IGNORECASE,
)
_CITY_MOSCOW = re.compile(
    r"\bмоскв[аеуы]\b|\bв\s+столиц[еу]\b|\bподмосков",
    re.IGNORECASE,
)

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

_STREET_LINE = re.compile(
    r"(?i)(?:"
    r"(?:ул\.?|улиц[аеыу]|пр-?т\.?|проспект[аеу]?|пер\.?|переул(?:ок|ке|ка)|"
    r"ш\.?|шоссе|б-?р\.?|бульвар[аеу]?|наб\.?|набережн(?:ая|ой|ую)|"
    r"пл\.?|площад[ьи]|проезд[аеу]?|алле[яию])"
    r"\s+[А-ЯЁа-яё0-9\- ]{3,40}"
    r"|"
    r"[А-ЯЁ][а-яё0-9\- ]{2,30}\s+"
    r"(?:ул\.?|улиц[аеыу]|пр-?т\.?|проспект|пер\.?|шоссе|бульвар|наб\.?|проезд)"
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
        "сегодня",
        "вечера",
        "утра",
    }
)


def is_moscow_context(text: str) -> bool:
    return bool(_CITY_MOSCOW.search(text))


def is_foreign_geo(text: str) -> bool:
    if not text.strip():
        return False
    return bool(_FOREIGN_GEO.search(text))


def is_non_moscow_geo(text: str) -> bool:
    if not text.strip():
        return False
    if is_foreign_geo(text):
        return True
    if is_moscow_context(text):
        return False
    return bool(_OTHER_RU_GEO.search(text))


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


def extract_street_lines(text: str) -> tuple[str, ...]:
    """Грубые кандидаты улиц из многострочных списков адресов (ЖЭК)."""
    if not text:
        return ()
    found: list[str] = []
    for match in _STREET_LINE.finditer(text):
        raw = re.sub(r"\s+", " ", match.group(0)).strip(" ,.;:")
        if len(raw) >= 5:
            found.append(raw)
    return tuple(dict.fromkeys(found))
