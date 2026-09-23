"""Детерминированный разбор русских окон активности для разметки time-датасета.

Не используется в runtime (runtime = только ONNX). Здесь — качественная
разметка train/val из реальных текстов MC/news/chat.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from re import Match

_MSK = timezone(timedelta(hours=3))

_MONTHS: dict[str, int] = {
    "января": 1,
    "январь": 1,
    "янв": 1,
    "февраля": 2,
    "февраль": 2,
    "фев": 2,
    "марта": 3,
    "март": 3,
    "апреля": 4,
    "апрель": 4,
    "апр": 4,
    "мая": 5,
    "май": 5,
    "июня": 6,
    "июнь": 6,
    "июля": 7,
    "июль": 7,
    "августа": 8,
    "август": 8,
    "сентября": 9,
    "сентябрь": 9,
    "сент": 9,
    "октября": 10,
    "октябрь": 10,
    "окт": 10,
    "ноября": 11,
    "ноябрь": 11,
    "ноя": 11,
    "декабря": 12,
    "декабрь": 12,
    "дек": 12,
}

_MONTH_ALT = (
    r"январ[яь]?|феврал[яь]?|марта?|апрел[яь]?|ма[йя]|июн[яь]?|июл[яь]?|"
    r"августа?|сентябр[яь]?|октябр[яь]?|ноябр[яь]?|декабр[яь]?"
)

_TIME_RE = re.compile(
    r"(?P<h>\d{1,2})[:.\-](?P<m>\d{2})(?::(?P<s>\d{2}))?",
)
_DMY_RE = re.compile(
    r"(?P<d>\d{1,2})[./](?P<m>\d{1,2})(?:[./](?P<y>\d{2,4}))?"
    r"(?:\s+(?P<h>\d{1,2})[:.\-](?P<min>\d{2})(?::(?P<s>\d{2}))?)?",
)
_DAY_MONTH_RE = re.compile(
    rf"(?P<d>\d{{1,2}})\s+(?P<mon>{_MONTH_ALT})"
    rf"(?:\s+(?P<y>\d{{4}}))?"
    rf"(?:\s+(?:в\s+)?(?P<h>\d{{1,2}})[:.\-](?P<min>\d{{2}}))?",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class WindowLabel:
    active_from: datetime | None
    active_to: datetime | None
    confidence: float
    pattern: str


def _norm(text: str) -> str:
    t = text.replace("\u00a0", " ").replace("\u202f", " ")
    t = t.replace("–", "-").replace("—", "-").replace("−", "-")
    return re.sub(r"[ \t]+", " ", t)


def _month_num(token: str) -> int | None:
    key = token.lower().rstrip(".")
    if key in _MONTHS:
        return _MONTHS[key]
    for name, num in _MONTHS.items():
        if key.startswith(name[:3]):
            return num
    return None


def _year_from(y: str | None, reference: datetime) -> int:
    if not y:
        return reference.year
    yi = int(y)
    if yi < 100:
        yi += 2000
    return yi


def _aware(dt: datetime, reference: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=reference.tzinfo or _MSK)
    return dt


def _combine(
    reference: datetime,
    *,
    day: int,
    month: int,
    year: int | None = None,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> datetime:
    y = year if year is not None else reference.year
    # если дата ушла далеко в прошлое относительно reference — вероятно следующий год
    # (для «1 января» в декабре); для «прошлых» дат в тексте оставляем как есть,
    # если разница < 180 дней назад — ок.
    try:
        dt = datetime(y, month, day, hour, minute, second, tzinfo=reference.tzinfo or _MSK)
    except ValueError:
        # 31.02 и т.п.
        day = min(day, 28)
        dt = datetime(y, month, day, hour, minute, second, tzinfo=reference.tzinfo or _MSK)
    # если offset > +400 дней — скорее прошлый год в тексте при позднем reference
    if (dt - reference).total_seconds() / 3600 > 400 and year is None:
        with contextlib.suppress(ValueError):
            dt = dt.replace(year=y - 1)
    # если offset < -400 дней — следующий год
    if (dt - reference).total_seconds() / 3600 < -400 and year is None:
        with contextlib.suppress(ValueError):
            dt = dt.replace(year=y + 1)
    return dt


def _parse_dmy_match(m: Match[str], reference: datetime) -> datetime | None:
    d = int(m.group("d"))
    mo = int(m.group("m"))
    y = _year_from(m.group("y"), reference) if m.groupdict().get("y") else None
    h = int(m.group("h")) if m.groupdict().get("h") and m.group("h") else 0
    mi = int(m.group("min")) if m.groupdict().get("min") and m.group("min") else 0
    s = int(m.group("s")) if m.groupdict().get("s") and m.group("s") else 0
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    if h > 23 or mi > 59:
        return None
    return _combine(reference, day=d, month=mo, year=y, hour=h, minute=mi, second=s)


def _parse_day_month_match(m: Match[str], reference: datetime) -> datetime | None:
    d = int(m.group("d"))
    mon = _month_num(m.group("mon"))
    if mon is None:
        return None
    y = int(m.group("y")) if m.group("y") else None
    h = int(m.group("h")) if m.group("h") else 0
    mi = int(m.group("min")) if m.group("min") else 0
    return _combine(reference, day=d, month=mon, year=y, hour=h, minute=mi)


def _parse_time_token(token: str) -> tuple[int, int] | None:
    m = _TIME_RE.fullmatch(token.strip())
    if not m:
        # 8.15 / 8-15 без ведущего нуля минут уже в _TIME_RE
        m2 = re.fullmatch(r"(\d{1,2})[.:](\d{2})", token.strip())
        if not m2:
            return None
        h, mi = int(m2.group(1)), int(m2.group(2))
    else:
        h, mi = int(m.group("h")), int(m.group("m"))
    if h > 23 or mi > 59:
        return None
    return h, mi


def _rel_day(reference: datetime, word: str) -> datetime:
    base = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    if word == "сегодня":
        return base
    if word == "завтра":
        return base + timedelta(days=1)
    if word == "послезавтра":
        return base + timedelta(days=2)
    return base


_EVENT_HINT = re.compile(
    r"(?i)отключ|опрессов|перекрыт|авари|ремонт|водоснаб|гвс|хвс|отоплен|"
    r"горяч\w*\s+вод|холодн\w*\s+вод|ограничен|работ\w+\s+на\s+|трактор|"
    r"чистк\w*\s+снег|лифт|электричеств|гроза|ветер|ливн|мероприят|"
    r"перекроют|закроют\s+движен"
)

_NON_EVENT = re.compile(
    r"(?i)показан\w*\s+сч[её]т|квитанц|оплат|коммунальн\w*\s+услуг|"
    r"госуслуги\s+дом|мошенничеств|клади\s+трубку|с\s+дн[её]м\s+рожден|"
    r"тариф\w*\s+на\s+коммуналь|кадастров|конкурс\s+|обучение\s+в\s+учебн|"
    r"тор\s+«?моя\s+школа|электросамокат"
)


def extract_window(text: str, reference: datetime) -> WindowLabel | None:
    """Вернуть окно или None, если уверенно разобрать нельзя."""
    raw = _norm(text)
    low = raw.lower()
    reference = _aware(reference, reference)

    # Явно не event-window (счета, тарифы, реклама) — даже если есть дата.
    if _NON_EVENT.search(low) and not _EVENT_HINT.search(low):
        return None

    # 1) с DD.MM[.YYYY][ HH:MM[:SS]] … (по|до|включение) DD.MM[.YYYY][ HH:MM]
    m = re.search(
        r"(?is)(?:отключен\w*\s+(?:услуг\w*\s+)?(?:гвс\s+)?)?с\s+"
        r"(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?(?:\s+\d{1,2}[:.\-]\d{2}(?::\d{2})?)?)"
        r".{0,120}?"
        r"(?:по|до|планируемое\s+время\s+включения|время\s+включения|включения?)\s*"
        r"(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?(?:\s+\d{1,2}[:.\-]\d{2}(?::\d{2})?)?)",
        raw,
    )
    if m:
        a = _DMY_RE.search(m.group(1))
        b = _DMY_RE.search(m.group(2))
        if a and b:
            af = _parse_dmy_match(a, reference)
            at = _parse_dmy_match(b, reference)
            if af and at and af <= at:
                return WindowLabel(af, at, 0.95, "dmy_range_s_po")

    # 2) с DD месяца [YYYY] по DD месяца [YYYY]
    m = re.search(
        rf"(?is)с\s+(\d{{1,2}}\s+(?:{_MONTH_ALT})(?:\s+\d{{4}})?)"
        rf".{{0,60}}?"
        rf"(?:по|до)\s+(\d{{1,2}}\s+(?:{_MONTH_ALT})(?:\s+\d{{4}})?)",
        raw,
    )
    if m:
        a = _DAY_MONTH_RE.search(m.group(1))
        b = _DAY_MONTH_RE.search(m.group(2))
        if a and b:
            af = _parse_day_month_match(a, reference)
            at = _parse_day_month_match(b, reference)
            if af and at:
                if at.hour == 0 and at.minute == 0:
                    at = at.replace(hour=23, minute=59)
                if af <= at:
                    return WindowLabel(af, at, 0.93, "day_month_range")

    # 3) DD - DD месяца [YYYY]  (опрессовка 7 - 21 июля 2026)
    m = re.search(
        rf"(?i)(\d{{1,2}})\s*-\s*(\d{{1,2}})\s+({_MONTH_ALT})(?:\s+(\d{{4}}))?",
        raw,
    )
    if m:
        mon = _month_num(m.group(3))
        if mon:
            y = int(m.group(4)) if m.group(4) else None
            af = _combine(reference, day=int(m.group(1)), month=mon, year=y, hour=0, minute=0)
            at = _combine(reference, day=int(m.group(2)), month=mon, year=y, hour=23, minute=59)
            if af <= at:
                return WindowLabel(af, at, 0.92, "day_dash_day_month")

    # 4) DD.MM - DD.MM  /  6.07-07.07  /  6.07-8.07
    m = re.search(
        r"(?i)(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)\s*-\s*"
        r"(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)",
        raw,
    )
    if m:
        a = _DMY_RE.fullmatch(m.group(1).strip()) or _DMY_RE.search(m.group(1))
        b = _DMY_RE.fullmatch(m.group(2).strip()) or _DMY_RE.search(m.group(2))
        if a and b:
            af = _parse_dmy_match(a, reference)
            at = _parse_dmy_match(b, reference)
            if af and at:
                if at.hour == 0 and at.minute == 0:
                    at = at.replace(hour=23, minute=59)
                if af <= at:
                    return WindowLabel(af, at, 0.9, "dmy_dash_dmy")

    # 5) завтра/сегодня/послезавтра с HH:MM до HH:MM
    m = re.search(
        r"(?i)\b(сегодня|завтра|послезавтра)\b.{0,40}?"
        r"(?:с\s+)?(\d{1,2}[:.\-]\d{2})\s*(?:до|-)\s*(\d{1,2}[:.\-]\d{2})",
        raw,
    )
    if m:
        day = _rel_day(reference, m.group(1).lower())
        t1 = _parse_time_token(m.group(2))
        t2 = _parse_time_token(m.group(3))
        if t1 and t2:
            af = day.replace(hour=t1[0], minute=t1[1])
            at = day.replace(hour=t2[0], minute=t2[1])
            if at < af:
                at += timedelta(days=1)
            return WindowLabel(af, at, 0.94, "rel_day_time_range")

    # 6a) завтра DD/MM [будет …]
    m = re.search(
        r"(?i)\b(сегодня|завтра|послезавтра)\b\s+(\d{1,2})/(\d{1,2})\b",
        raw,
    )
    if m:
        day = _rel_day(reference, m.group(1).lower())
        # дата в тексте уточняет день/месяц
        with contextlib.suppress(ValueError):
            day = day.replace(day=int(m.group(2)), month=int(m.group(3)))
        af = day.replace(hour=8, minute=0)
        at = day.replace(hour=14, minute=0)
        return WindowLabel(af, at, 0.84, "rel_day_slash_date")

    # 6b) завтра/сегодня в HH:MM  (одноразовое событие → окно ~4ч)
    m = re.search(
        r"(?i)\b(сегодня|завтра|послезавтра)\b(?:\s+\d{1,2}/\d{1,2})?\s+"
        r"(?:в\s+|с\s+)?(\d{1,2}[:.\-]\d{2})\b",
        raw,
    )
    if m and not re.search(r"(?i)\bдо\s+\d{1,2}[:.\-]\d{2}", raw[m.start() : m.start() + 80]):
        day = _rel_day(reference, m.group(1).lower())
        t1 = _parse_time_token(m.group(2))
        if t1:
            af = day.replace(hour=t1[0], minute=t1[1])
            at = af + timedelta(hours=4)
            return WindowLabel(af, at, 0.85, "rel_day_time_start")

    # 6c) завтра с HH часов (без минут)
    m = re.search(
        r"(?i)\b(сегодня|завтра|послезавтра)\b.{0,30}?с\s+(\d{1,2})\s*часов?",
        raw,
    )
    if m:
        day = _rel_day(reference, m.group(1).lower())
        h = int(m.group(2))
        if 0 <= h <= 23:
            af = day.replace(hour=h, minute=0)
            at = af + timedelta(hours=7)
            return WindowLabel(af, at, 0.83, "rel_day_from_hour")

    # 6d) в четверг/пятницу, DD месяца
    m = re.search(
        rf"(?i)(?:в\s+)?(?:понедельник|вторник|сред[уа]|четверг|пятниц[уа]|суббот[уа]|воскресенье),?\s+"
        rf"(\d{{1,2}}\s+(?:{_MONTH_ALT}))",
        raw,
    )
    if m:
        a = _DAY_MONTH_RE.search(m.group(1))
        if a:
            af = _parse_day_month_match(a, reference)
            if af:
                af = af.replace(hour=8, minute=0)
                at = af.replace(hour=20, minute=0)
                return WindowLabel(af, at, 0.87, "weekday_day_month")

    # 7) до завтра до HH / до завтра
    m = re.search(
        r"(?i)до\s+завтра(?:\s+до\s+(\d{1,2})(?:[:.\-]?(\d{2})|часов?)?)?",
        raw,
    )
    if m:
        day = _rel_day(reference, "завтра")
        if m.group(1):
            h = int(m.group(1))
            mi = int(m.group(2) or 0)
            at = day.replace(hour=min(h, 23), minute=mi)
        else:
            at = day.replace(hour=23, minute=59)
        return WindowLabel(None, at, 0.88, "until_tomorrow")

    # 8) до DD.MM[.YYYY][ HH:MM]  /  до DD месяца (только event-контекст)
    if _EVENT_HINT.search(low):
        m = re.search(
            r"(?i)(?:до|по)\s+"
            r"(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?(?:\s+\d{1,2}[:.\-]\d{2}(?::\d{2})?)?)",
            raw,
        )
        if m and not re.search(r"(?i)\bс\s+\d{1,2}[./]\d{1,2}", raw):
            a = _DMY_RE.search(m.group(1))
            if a:
                at = _parse_dmy_match(a, reference)
                if at:
                    if not re.search(r"\d{1,2}[:.\-]\d{2}", m.group(1)):
                        at = at.replace(hour=23, minute=59)
                    return WindowLabel(None, at, 0.86, "until_dmy")

        m = re.search(
            rf"(?i)(?:до|по)\s+(\d{{1,2}}\s+(?:{_MONTH_ALT})(?:\s+\d{{4}})?)",
            raw,
        )
        if m and not re.search(rf"(?i)\bс\s+\d{{1,2}}\s+(?:{_MONTH_ALT})", raw):
            a = _DAY_MONTH_RE.search(m.group(1))
            if a:
                at = _parse_day_month_match(a, reference)
                if at:
                    at = at.replace(hour=23, minute=59)
                    return WindowLabel(None, at, 0.86, "until_day_month")

    # 9) с DD.MM[.YYYY][ HH:MM] без конца — только event
    if _EVENT_HINT.search(low):
        m = re.search(
            r"(?i)\bс\s+"
            r"(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?(?:\s+\d{1,2}[:.\-]\d{2}(?::\d{2})?)?)"
            r"(?!\s*-\s*\d)",
            raw,
        )
        if m and not re.search(r"(?i)(?:по|до|включения?)\s+\d{1,2}[./]\d{1,2}", raw):
            a = _DMY_RE.search(m.group(1))
            if a:
                af = _parse_dmy_match(a, reference)
                if af:
                    return WindowLabel(af, None, 0.8, "from_dmy_only")

        # 10) с DD месяца без конца
        m = re.search(
            rf"(?i)\bс\s+(\d{{1,2}}\s+(?:{_MONTH_ALT})(?:\s+\d{{4}})?)"
            rf"(?!\s*(?:по|до)\s+\d)",
            raw,
        )
        if m and not re.search(rf"(?i)(?:по|до)\s+\d{{1,2}}\s+(?:{_MONTH_ALT})", raw):
            a = _DAY_MONTH_RE.search(m.group(1))
            if a:
                af = _parse_day_month_match(a, reference)
                if af:
                    return WindowLabel(af, None, 0.8, "from_day_month_only")

    # 11) с HH:MM до HH:MM (без дня) — сегодня относительно reference
    m = re.search(
        r"(?i)(?:^|[^\d])с\s+(\d{1,2}[:.\-]\d{2})\s*(?:до|-)\s*(\d{1,2}[:.\-]\d{2})",
        raw,
    )
    if m and not re.search(
        r"(?i)\b(сегодня|завтра|послезавтра|\d{1,2}[./]\d{1,2}|\d{1,2}\s+(?:" + _MONTH_ALT + r"))",
        low,
    ):
        t1 = _parse_time_token(m.group(1))
        t2 = _parse_time_token(m.group(2))
        if t1 and t2:
            day = reference.replace(second=0, microsecond=0)
            af = day.replace(hour=t1[0], minute=t1[1])
            at = day.replace(hour=t2[0], minute=t2[1])
            if at <= af:
                at += timedelta(days=1)
            # если reference уже после конца — сдвиг на завтра
            if reference > at + timedelta(hours=1):
                af += timedelta(days=1)
                at += timedelta(days=1)
            return WindowLabel(af, at, 0.75, "same_day_time_range")

    # 12) днем DD / ночью и днем DD месяца (погода МЧС) → from day start, to next evening
    m = re.search(
        rf"(?i)дн[её]м\s+(\d{{1,2}})(?:,\s*ночью\s+и\s+дн[её]м\s+(\d{{1,2}}))?\s+"
        rf"({_MONTH_ALT})",
        raw,
    )
    if m:
        mon = _month_num(m.group(3))
        if mon:
            d1 = int(m.group(1))
            d2 = int(m.group(2)) if m.group(2) else d1
            af = _combine(reference, day=d1, month=mon, hour=0, minute=0)
            at = _combine(reference, day=d2, month=mon, hour=23, minute=59)
            return WindowLabel(af, at, 0.82, "weather_day_span")

    return None


def looks_like_no_window(text: str) -> bool:
    """Эвристика: текст без временного окна события (для neither-примеров)."""
    low = _norm(text).lower()
    if extract_window(text, datetime(2026, 6, 1, 12, 0, tzinfo=_MSK)) is not None:
        return False
    noise = (
        "показания",
        "квитанц",
        "оплат",
        "госуслуги дом",
        "поздравля",
        "с днём рождения",
        "с днем рождения",
        "мошенничеств",
        "клади трубку",
        "голосование за благоустройство",
        "передать показания",
    )
    if any(x in low for x in noise):
        return True
    # нет явных маркеров времени
    markers = (
        r"\d{1,2}[./]\d{1,2}",
        r"\d{1,2}[:.\-]\d{2}",
        r"завтра",
        r"сегодня",
        r"послезавтра",
        _MONTH_ALT,
        r"\bс\s+\d",
        r"\bдо\s+\d",
        r"\bпо\s+\d",
    )
    return not any(re.search(p, low, re.IGNORECASE) for p in markers)
