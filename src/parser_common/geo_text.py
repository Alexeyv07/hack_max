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
    r"новосибирск|екатеринбург|казан[ьие]|челябинск|"
    # самар[аеуы] — не «Самарская» (московская улица); область — отдельно
    r"самар[аеуыи]\b|самарск\w*\s+област|"
    r"нижегород|нижн\w+\s+новгород|ростов[-\s]?на[-\s]?дону|"
    r"краснодар|воронеж|пермь|волгоград|красноярск|уф[аые]|"
    r"владивосток|хабаровск|иркутск|тюмен|омск|томск|"
    r"саратов|тольятти|ижевск|барнаул|ульяновск|"
    r"ярославл|владикавказ|махачкал|грозн|"
    r"калининград|мурманск|архангельск|сочи|"
    # рязан[ьи] — не «Рязанский» проспект в Москве
    r"рязан[ьи]\b|рязанск\w*\s+област|тул[аые]|калуг|твер[ьи]|владимир|смоленск|"
    r"липецк|ор[её]л|курск|белгород|пенз|тамбов|"
    r"астрахан|киров|чебоксар|иванов|брянск|магнитогорск|"
    r"набережн\w+\s+челны|стерлитамак|нижнекамск"
    r")\w*",
)

# Голые названия городов (без «улица …») — нельзя отдавать в StreetCatalog:
# spaCy «Самара» иначе fuzzy → «Самарская» (Москва).
_BARE_OTHER_CITIES = frozenset(
    {
        "самара",
        "самаре",
        "самару",
        "самары",
        "самарой",
        "казань",
        "казани",
        "казанью",
        "новосибирск",
        "новосибирска",
        "екатеринбург",
        "екатеринбурга",
        "челябинск",
        "челябинска",
        "краснодар",
        "краснодара",
        "воронеж",
        "воронежа",
        "пермь",
        "перми",
        "волгоград",
        "волгограда",
        "красноярск",
        "красноярска",
        "уфа",
        "уфы",
        "омск",
        "омска",
        "томск",
        "томска",
        "саратов",
        "саратова",
        "тольятти",
        "ижевск",
        "ижевска",
        "барнаул",
        "барнаула",
        "ульяновск",
        "ульяновска",
        "ярославль",
        "ярославля",
        "сочи",
        "тюмень",
        "тюмени",
        "петербург",
        "петербурга",
        "спб",
        "ленинград",
        "ленинграда",
        "санкт-петербург",
        "санкт петербург",
        "нижний новгород",
        "ростов-на-дону",
        "ростов на дону",
        "владивосток",
        "владивостока",
        "хабаровск",
        "хабаровска",
        "иркутск",
        "иркутска",
        "рязань",
        "рязани",
        "тула",
        "тулы",
        "калуга",
        "калуги",
        "тверь",
        "твери",
        "владимир",
        "владимира",
        "смоленск",
        "смоленска",
        "липецк",
        "липецка",
        "орел",
        "орёл",
        "орла",
        "курск",
        "курска",
        "белгород",
        "белгорода",
        "пенза",
        "пензы",
        "тамбов",
        "тамбова",
        "астрахань",
        "астрахани",
        "киров",
        "кирова",
        "чебоксары",
        "иваново",
        "брянск",
        "брянска",
        "магнитогорск",
        "магнитогорска",
    }
)

_STREET_TYPE_MARKERS = frozenset(
    {
        "ул",
        "улица",
        "улице",
        "улицы",
        "пр",
        "проспект",
        "пер",
        "переулок",
        "шоссе",
        "бульвар",
        "наб",
        "набережная",
        "площадь",
        "проезд",
        "аллея",
    }
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


def has_other_ru_city(text: str) -> bool:
    """В тексте есть другой город РФ (Самара, Казань, …)."""
    if not text.strip():
        return False
    return bool(_OTHER_RU_GEO.search(text))


def is_non_moscow_geo(text: str) -> bool:
    """
    Чужой регион / страна → не пишем в московские events.

    «Только Самара» → True. «Москва + Самара» → False (разрешаем
    московские улицы), но голый топоним «Самара» режется из hints.
    """
    if not text.strip():
        return False
    if is_foreign_geo(text):
        return True
    return has_other_ru_city(text) and not is_moscow_context(text)


def is_allowed_project_city(city: str | None) -> bool:
    """В addresses проекта только Москва / область (не создаём Самару и т.п.)."""
    if not city or not city.strip():
        return False
    norm = city.lower().replace("ё", "е").strip()
    if "москв" in norm:
        return True
    return "московск" in norm and "област" in norm


def is_bare_other_city_hint(hint: str) -> bool:
    """
    Голый топоним чужого города без типа улицы.

    «Самара» → True (нельзя в StreetCatalog).
    «улица Самарская» / «Самарская» как улица → False.
    """
    raw = hint.lower().replace("ё", "е").strip()
    raw = re.sub(r"[^\w\s\-]+", " ", raw, flags=re.UNICODE)
    tokens = [t for t in raw.split() if t]
    if not tokens:
        return False
    if any(t in _STREET_TYPE_MARKERS for t in tokens):
        return False
    joined = " ".join(tokens)
    if joined in _BARE_OTHER_CITIES:
        return True
    # однословный город: «Самара»
    return len(tokens) == 1 and tokens[0] in _BARE_OTHER_CITIES


def filter_moscow_location_hints(hints: list[str]) -> list[str]:
    """Убрать из hints голые чужие города и foreign-маркеры."""
    out: list[str] = []
    for hint in hints:
        if not hint or not hint.strip():
            continue
        if is_bare_other_city_hint(hint):
            continue
        if is_foreign_geo(hint) and not any(
            t in hint.lower() for t in ("ул", "проспект", "переул", "шоссе")
        ):
            continue
        out.append(hint)
    return out


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
        if is_bare_other_city_hint(cleaned):
            continue
        hints.append(cleaned)

    for match in _NAKED_STREET.finditer(text):
        name = match.group("name")
        if name.lower() in _STOP_WORDS or len(name) < 4:
            continue
        if is_foreign_geo(name):
            continue
        if is_bare_other_city_hint(name):
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
        if len(raw) >= 5 and not is_bare_other_city_hint(raw):
            found.append(raw)
    return tuple(dict.fromkeys(found))
