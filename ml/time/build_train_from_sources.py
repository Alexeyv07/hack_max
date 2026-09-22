"""Сборка качественного time-датасета из bootstrap_events + чатов MAX.

Запуск из корня репо:
  python ml/time/build_train_from_sources.py
  python ml/time/build_train_from_sources.py --dry-run

Пишет:
  ml/time/data/train.jsonl
  ml/time/data/val.jsonl
  ml/time/data/label_report.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = HERE / "data"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from dataset_io import TimeExample, bound_counts, write_jsonl  # noqa: E402
from ru_window import WindowLabel, extract_window, looks_like_no_window  # noqa: E402

_MSK = timezone(timedelta(hours=3))

DEFAULT_BOOTSTRAP = ROOT / "src" / "parser_common" / "data" / "bootstrap_events.jsonl.gz"
DEFAULT_CHATS = [
    Path(
        r"C:\Users\iosh\Downloads\Telegram Desktop"
        r"\max_chat_69138407628804_2026-09-18"
        r"\max_chat_69138407628804_2026-09-18\messages.json"
    ),
    Path(r"C:\Users\iosh\Downloads\max_chat_sulimova_47a_2026-09-21.json"),
    Path(r"C:\Users\iosh\Downloads\max_chat_komsomolskiy_30_2026-09-21.json"),
]

# Клип offsets: модель должна учить локальные окна (ЖКХ / ближайшие дни), не годы.
MAX_ABS_OFFSET_H = 720.0  # 30 суток
MIN_CONF_KEEP = 0.8

_MONTH_RU = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_MSK)
    return dt


_RU_DATE_LABEL = re.compile(
    r"(?P<d>\d{1,2})\s+"
    r"(?P<mon>января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)"
    r"(?:\s+(?P<y>\d{4}))?",
    re.IGNORECASE,
)
_MON_MAP = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def _parse_ru_date_label(
    label: str, *, default_year: int, hour: int = 12, minute: int = 0
) -> datetime | None:
    m = _RU_DATE_LABEL.search(label.strip())
    if not m:
        return None
    y = int(m.group("y")) if m.group("y") else default_year
    mon = _MON_MAP[m.group("mon").lower()]
    d = int(m.group("d"))
    try:
        return datetime(y, mon, d, hour, minute, tzinfo=_MSK)
    except ValueError:
        return None


def _parse_chat_time(time_text: str | None) -> tuple[int, int]:
    if not time_text:
        return 12, 0
    m = re.match(r"(\d{1,2}):(\d{2})", time_text.strip())
    if not m:
        return 12, 0
    return int(m.group(1)), int(m.group(2))


def _offset_ok(ref: datetime, af: datetime | None, at: datetime | None) -> bool:
    for dt in (af, at):
        if dt is None:
            continue
        h = abs((dt - ref).total_seconds() / 3600.0)
        if h > MAX_ABS_OFFSET_H:
            return False
    return True


def _row(
    text: str,
    reference: datetime,
    af: datetime | None,
    at: datetime | None,
    source: str,
    *,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": re.sub(r"\s+", " ", text).strip()[:1200],
        "reference": reference.isoformat(),
        "active_from": af.isoformat() if af else None,
        "active_to": at.isoformat() if at else None,
        "source": source,
    }
    if meta:
        payload["_meta"] = meta
    return payload


def _from_label(
    text: str,
    reference: datetime,
    label: WindowLabel,
    source: str,
) -> dict[str, Any] | None:
    if label.confidence < MIN_CONF_KEEP:
        return None
    if not _offset_ok(reference, label.active_from, label.active_to):
        return None
    if label.active_from is None and label.active_to is None:
        return None
    return _row(
        text,
        reference,
        label.active_from,
        label.active_to,
        source,
        meta={"pattern": label.pattern, "confidence": label.confidence},
    )


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def load_bootstrap_events(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            raw = json.loads(line)
            title = (raw.get("title") or "").strip()
            body = (raw.get("body") or "").strip()
            # title часто дублирует body — берём более информативный кусок
            if body and title and title.lower() in body.lower():
                text = body
            elif title and body:
                text = f"{title}. {body}"
            else:
                text = title or body
            text = text.strip()
            if len(text) < 40:
                continue
            pub = _parse_iso(raw.get("published_at"))
            if pub is None:
                continue
            # reference в MSK для единообразия с чатами
            ref = pub.astimezone(_MSK)
            src = str(raw.get("source") or "news")
            rows.append({"text": text, "reference": ref, "source": src})
    return rows


def load_chat_messages(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    export_year = 2026
    export_date = raw.get("export_date") or (raw.get("parsed_at") or "")[:10]
    if isinstance(export_date, str) and len(export_date) >= 4 and export_date[:4].isdigit():
        export_year = int(export_date[:4])

    out: list[dict[str, Any]] = []
    for msg in raw.get("messages") or []:
        if msg.get("is_service") or msg.get("type") == "system":
            continue
        text = (msg.get("body_text") or msg.get("text") or msg.get("display_text") or "").strip()
        if len(text) < 20:
            continue
        date_label = msg.get("date_label") or msg.get("date") or ""
        hour, minute = _parse_chat_time(msg.get("time_text"))
        ref = _parse_ru_date_label(
            str(date_label), default_year=export_year, hour=hour, minute=minute
        )
        if ref is None:
            # fallback: parsed_at чата
            ref = _parse_iso(raw.get("parsed_at") or raw.get("saved_at_utc"))
            if ref is None:
                continue
            ref = ref.astimezone(_MSK)
        out.append(
            {
                "text": text,
                "reference": ref,
                "source": "chat",
                "chat_title": raw.get("chat_title"),
            }
        )
    return out


def label_candidates(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    labeled: list[dict[str, Any]] = []
    neither: list[dict[str, Any]] = []
    for item in items:
        text = item["text"]
        ref: datetime = item["reference"]
        source = item["source"]
        win = extract_window(text, ref)
        if win is not None:
            row = _from_label(text, ref, win, source)
            if row is not None:
                labeled.append(row)
                continue
        if looks_like_no_window(text):
            neither.append(
                _row(
                    text,
                    ref,
                    None,
                    None,
                    source,
                    meta={"pattern": "neither_heuristic", "confidence": 0.7},
                )
            )
    return labeled, neither


# ---------------------------------------------------------------------------
# Curated gold (ручная разметка самых явных чат-кейсов)
# ---------------------------------------------------------------------------


def curated_gold() -> list[dict[str, Any]]:
    """Явные окна из чатов — эталон (не полагаемся только на парсер)."""
    gold: list[tuple[str, str, str | None, str | None]] = [
        (
            "Горького 32 завтра в 8.15. Уже трактор снова чистить снег. Просьба убрать все машины",
            "2026-02-02T15:53:00+03:00",
            "2026-02-03T08:15:00+03:00",
            "2026-02-03T12:15:00+03:00",
        ),
        (
            "Горького 32 завтра в 8.15 приедет трактор, для уборки снена. Просьба убрать машины.",
            "2026-02-18T17:26:00+03:00",
            "2026-02-19T08:15:00+03:00",
            "2026-02-19T12:15:00+03:00",
        ),
        (
            "Соседи завтра с 8.00 будет трактор чистить снег во дворах жэу 4. Просьба убрать свои машины",
            "2026-03-05T15:05:00+03:00",
            "2026-03-06T08:00:00+03:00",
            "2026-03-06T12:00:00+03:00",
        ),
        (
            "добрый день завтра 6/3 будет очистка снега на придомовой территории трактор убрать все машины",
            "2026-03-05T15:10:00+03:00",
            "2026-03-06T08:00:00+03:00",
            "2026-03-06T14:00:00+03:00",
        ),
        (
            "С 16 июня по 1 июля 2 этап опрессовки. Максимальный срок отключения — две недели.",
            "2026-06-10T12:04:00+03:00",
            "2026-06-16T00:00:00+03:00",
            "2026-07-01T23:59:00+03:00",
        ),
        (
            "График опрессовки на июль 2026 г. 7 - 21 июля 2026 г. В указанный период будет отсутствовать горячее водоснабжение.",
            "2026-07-06T12:00:00+03:00",
            "2026-07-07T00:00:00+03:00",
            "2026-07-21T23:59:00+03:00",
        ),
        (
            "Внимание! отключении услуги ГВС с 23.07.2026 10:00:00 на мкд. Планируемое время включения 27.07.2026 18:00:00 — работы проводит УСТЭК",
            "2026-07-22T12:00:00+03:00",
            "2026-07-23T10:00:00+03:00",
            "2026-07-27T18:00:00+03:00",
        ),
        (
            "Уведомляем об отключении услуг(и) ГВС с 01.08.2026 9:00:00 для объекта(ов): Ж/ДОМ УЛ.СУЛИМОВА 47А",
            "2026-08-01T08:00:00+03:00",
            "2026-08-01T09:00:00+03:00",
            None,
        ),
        (
            "Отключение горячей воды продлили до завтра до 23часов! работы ведёт УСТЭК",
            "2026-08-04T12:00:00+03:00",
            None,
            "2026-08-05T23:00:00+03:00",
        ),
        (
            "Уведомляем о продлении отключения услуг(и) ГВС до 05.08.2026 23:00:00 для объекта(ов)",
            "2026-08-05T10:00:00+03:00",
            None,
            "2026-08-05T23:00:00+03:00",
        ),
        (
            "В МУП «ПОВВ» сообщили, что черная вода может течь до 6 августа",
            "2026-08-05T12:00:00+03:00",
            None,
            "2026-08-06T23:59:00+03:00",
        ),
        (
            "Отключение будет проходить поэтапно, до 8 мая. Если после отключения батареи остаются горячими — сообщите в УК.",
            "2026-05-04T11:26:00+03:00",
            None,
            "2026-05-08T23:59:00+03:00",
        ),
        (
            "Завтра, 8 июля, с 09:30 до 17:00 в связи с плановыми работами на водоводе будет временно прекращено водоснабжение по адресам: пр-кт Комсомольский, 30.",
            "2026-07-07T12:00:00+03:00",
            "2026-07-08T09:30:00+03:00",
            "2026-07-08T17:00:00+03:00",
        ),
        (
            "Добрый день! Сейчас позвонили из гор водоканала. Завтра будет отсутствовать холодная и горячая вода с 9.30 до 17.00",
            "2026-07-07T15:00:00+03:00",
            "2026-07-08T09:30:00+03:00",
            "2026-07-08T17:00:00+03:00",
        ),
        (
            "Завтра с 10 часов будут работать газовщики",
            "2026-07-07T18:00:00+03:00",
            "2026-07-08T10:00:00+03:00",
            "2026-07-08T17:00:00+03:00",
        ),
        (
            "6.07-07.07 с первого по третий подъезд / 07.07-08.07 с четвертого по шестой",
            "2026-07-03T12:00:00+03:00",
            "2026-07-06T00:00:00+03:00",
            "2026-07-07T23:59:00+03:00",
        ),
        (
            "С 16-30 июня не будет",
            "2026-06-15T12:00:00+03:00",
            "2026-06-16T00:00:00+03:00",
            "2026-06-30T23:59:00+03:00",
        ),
        (
            "Порывы ветра до 20 м/с ожидаются на территории Челябинской области днем 27 мая.",
            "2026-05-26T13:57:00+03:00",
            "2026-05-27T00:00:00+03:00",
            "2026-05-27T23:59:00+03:00",
        ),
        (
            "Днем 27, ночью и днем 28 июня в отдельных районах Челябинской области ожидаются сильные дожди, грозы.",
            "2026-06-26T15:25:00+03:00",
            "2026-06-27T00:00:00+03:00",
            "2026-06-28T23:59:00+03:00",
        ),
        (
            "в четверг, 14 мая, на инженерных сетях будут проводить ремонт водовода №4. Холодную воду не отключат полностью.",
            "2026-05-13T12:19:00+03:00",
            "2026-05-14T08:00:00+03:00",
            "2026-05-14T20:00:00+03:00",
        ),
        # neither — полезный негатив
        (
            "Пора передать показания счётчиков за апрель. Внесите данные показаний приборов учета по воде и теплу.",
            "2026-04-21T22:04:00+03:00",
            None,
            None,
        ),
        (
            "Счета за март уже доступны в приложении «Госуслуги Дом»",
            "2026-04-09T20:23:00+03:00",
            None,
            None,
        ),
        (
            "Внимание! информируем вас о контенте по противодействию телефонному мошенничеству «Клади трубку 2.0».",
            "2026-08-31T08:21:00+03:00",
            None,
            None,
        ),
        (
            "Соседи сверху не предупреждают. По статистике страховых случаев за 2025 год, 38% повреждений квартир произошли по вине соседей сверху.",
            "2026-07-28T12:00:00+03:00",
            None,
            None,
        ),
    ]
    rows: list[dict[str, Any]] = []
    for text, ref_s, af_s, at_s in gold:
        ref = _parse_iso(ref_s)
        assert ref is not None
        af = _parse_iso(af_s)
        at = _parse_iso(at_s)
        rows.append(
            _row(
                text,
                ref,
                af,
                at,
                "chat",
                meta={"pattern": "curated_gold", "confidence": 1.0},
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Realistic synthetic (короткие горизонты, форматы как в чатах/ЖКХ)
# ---------------------------------------------------------------------------


def build_realistic_synthetic(n: int = 900, seed: int = 33) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    places = [
        "ул. Ленина, д. 10",
        "пр. Комсомольский, 30",
        "ул. Сулимова, 47А",
        "ул. Горького, 32",
        "районе Нагатино",
        "ЖК Рассвет",
        "пер. Садовый",
    ]
    rows: list[dict[str, Any]] = []

    def fmt_dmy(dt: datetime) -> str:
        return f"{dt.day:02d}.{dt.month:02d}.{dt.year}"

    def fmt_hm(dt: datetime) -> str:
        return f"{dt.hour:02d}:{dt.minute:02d}"

    def fmt_day_mon(dt: datetime) -> str:
        return f"{dt.day} {_MONTH_RU[dt.month]}"

    kinds = ["both"] * 5 + ["from_only"] * 2 + ["to_only"] * 2 + ["neither"] * 3

    for _ in range(n):
        kind = rng.choice(kinds)
        ref = datetime(
            2026,
            rng.randint(1, 9),
            rng.randint(1, 28),
            rng.choice([8, 10, 12, 15, 18, 20]),
            rng.choice([0, 15, 30]),
            tzinfo=_MSK,
        )
        place = rng.choice(places)
        start_h = rng.choice([0, 6, 12, 18, 24, 36, 48, 72, 96, 120, -6, -12])
        dur_h = rng.choice([4, 6, 8, 12, 24, 36, 48, 72, 120, 168, 240, 336])
        af = (ref + timedelta(hours=start_h)).replace(second=0, microsecond=0)
        af = af.replace(minute=rng.choice([0, 15, 30]))
        at = af + timedelta(hours=dur_h)
        at = at.replace(minute=rng.choice([0, 30]))

        if kind == "neither":
            text = rng.choice(
                [
                    f"Напоминаем жителям {place}: передайте показания счётчиков до 25 числа.",
                    f"Счета за ЖКУ по {place} доступны в приложении Госуслуги Дом.",
                    f"Аварийная бригада выехала на {place}, сроки уточняются.",
                    f"Соседи, не оставляйте мусор в подъезде на {place}.",
                    "Информируем о противодействии мошенничеству. Не сообщайте коды из СМС.",
                ]
            )
            rows.append(_row(text, ref, None, None, "synthetic", meta={"pattern": "synth_neither"}))
            continue

        if kind == "from_only":
            text = rng.choice(
                [
                    f"С {fmt_dmy(af)} {fmt_hm(af)} на {place} начнут промывку сетей",
                    f"С {fmt_day_mon(af)} на {place} стартует ремонт теплосети",
                    f"Без отопления на {place} с {fmt_dmy(af)} {fmt_hm(af)} до устранения аварии",
                ]
            )
            rows.append(_row(text, ref, af, None, "synthetic", meta={"pattern": "synth_from"}))
            continue

        if kind == "to_only":
            text = rng.choice(
                [
                    f"Горячую воду на {place} вернут до {fmt_dmy(at)} {fmt_hm(at)}",
                    f"Ограничения на {place} действуют до {fmt_day_mon(at)}",
                    f"Отключение ГВС продлили до {fmt_dmy(at)} {fmt_hm(at)}",
                    f"Чёрная вода может течь до {fmt_day_mon(at)}",
                ]
            )
            rows.append(_row(text, ref, None, at, "synthetic", meta={"pattern": "synth_to"}))
            continue

        # both — разные форматы, в т.ч. «завтра»
        style = rng.randint(0, 5)
        if style == 0:
            # absolute dmy+time
            text = (
                f"Отключение ГВС с {fmt_dmy(af)} {fmt_hm(af)} "
                f"планируемое время включения {fmt_dmy(at)} {fmt_hm(at)}. Адрес: {place}"
            )
        elif style == 1:
            text = (
                f"С {fmt_day_mon(af)} по {fmt_day_mon(at)} опрессовка на {place}. "
                f"Горячая вода будет отсутствовать."
            )
        elif style == 2 and 0 <= (af.date() - ref.date()).days <= 1 and af.date() != at.date():
            # same-day window tomorrow
            day_word = "завтра" if af.date() == (ref.date() + timedelta(days=1)) else "сегодня"
            # force same calendar day window
            at2 = af.replace(hour=rng.choice([16, 17, 18, 20]), minute=0)
            if at2 <= af:
                at2 = af + timedelta(hours=6)
            text = (
                f"{day_word.capitalize()} с {fmt_hm(af)} до {fmt_hm(at2)} на {place} "
                f"отключат воду в связи с плановыми работами"
            )
            at = at2
        elif style == 3 and af.month == at.month:
            text = (
                f"График опрессовки: {af.day} - {at.day} {_MONTH_RU[af.month]} {af.year}. "
                f"Отключение ГВС на {place}."
            )
            af = af.replace(hour=0, minute=0)
            at = at.replace(hour=23, minute=59)
        elif style == 4:
            # завтра в HH:MM short window
            tomorrow = (ref + timedelta(days=1)).replace(
                hour=rng.choice([8, 9, 10]),
                minute=rng.choice([0, 15, 30]),
                second=0,
                microsecond=0,
            )
            af = tomorrow
            at = af + timedelta(hours=4)
            text = f"{place}: завтра в {fmt_hm(af)} приедет трактор чистить снег. Уберите машины."
        else:
            text = (
                f"Перекрытие у {place} с {fmt_dmy(af)} {fmt_hm(af)} по {fmt_dmy(at)} {fmt_hm(at)}"
            )

        if not _offset_ok(ref, af, at):
            continue
        rows.append(_row(text, ref, af, at, "synthetic", meta={"pattern": f"synth_both_{style}"}))

    return rows


# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------


def _to_example(row: dict[str, Any]) -> TimeExample:
    return TimeExample(
        text=row["text"],
        reference=_parse_iso(row["reference"]) or datetime.now(tz=_MSK),
        active_from=_parse_iso(row.get("active_from")),
        active_to=_parse_iso(row.get("active_to")),
        source=row.get("source"),
    )


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = re.sub(r"\s+", " ", row["text"]).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _strip_meta(rows: list[dict[str, Any]]) -> list[TimeExample]:
    return [_to_example(r) for r in rows]


def _balance_neither(
    positive: list[dict[str, Any]],
    neither_pool: list[dict[str, Any]],
    *,
    ratio: float,
    rng: random.Random,
) -> list[dict[str, Any]]:
    target = int(len(positive) * ratio)
    pool = neither_pool[:]
    rng.shuffle(pool)
    return positive + pool[:target]


def build(
    *,
    bootstrap_path: Path,
    chat_paths: list[Path],
    synthetic_n: int,
    neither_ratio: float,
    val_ratio: float,
    seed: int,
) -> tuple[list[TimeExample], list[TimeExample], dict[str, Any]]:
    rng = random.Random(seed)

    bootstrap_items = load_bootstrap_events(bootstrap_path) if bootstrap_path.is_file() else []
    chat_items: list[dict[str, Any]] = []
    for p in chat_paths:
        if p.is_file():
            chat_items.extend(load_chat_messages(p))

    boot_pos, boot_neg = label_candidates(bootstrap_items)
    chat_pos, chat_neg = label_candidates(chat_items)
    gold = curated_gold()
    synth = build_realistic_synthetic(n=synthetic_n, seed=seed)

    # gold и auto-labeled; neither из реальных источников предпочтительнее синтетики
    positives = _dedupe(
        gold
        + chat_pos
        + boot_pos
        + [r for r in synth if r.get("active_from") or r.get("active_to")]
    )
    neither_real = _dedupe(
        chat_neg
        + boot_neg
        + [r for r in gold if not r.get("active_from") and not r.get("active_to")]
    )
    neither_synth = [r for r in synth if not r.get("active_from") and not r.get("active_to")]

    all_rows = _balance_neither(
        positives, neither_real + neither_synth, ratio=neither_ratio, rng=rng
    )
    all_rows = _dedupe(all_rows)
    rng.shuffle(all_rows)

    examples = _strip_meta(all_rows)

    # split stratified
    from sklearn.model_selection import train_test_split

    strata = []
    for r in examples:
        if r.has_from and r.has_to:
            strata.append("both")
        elif r.has_from:
            strata.append("from")
        elif r.has_to:
            strata.append("to")
        else:
            strata.append("none")
    try:
        train_rows, val_rows = train_test_split(
            examples, test_size=val_ratio, random_state=seed, stratify=strata
        )
    except ValueError:
        train_rows, val_rows = train_test_split(examples, test_size=val_ratio, random_state=seed)

    report = {
        "bootstrap_events": len(bootstrap_items),
        "chat_messages": len(chat_items),
        "labeled": {
            "bootstrap_pos": len(boot_pos),
            "chat_pos": len(chat_pos),
            "gold": len(gold),
            "synthetic_pos": sum(1 for r in synth if r.get("active_from") or r.get("active_to")),
            "neither_real": len(neither_real),
            "total": len(examples),
            "train": len(train_rows),
            "val": len(val_rows),
        },
        "bounds_train": bound_counts(list(train_rows)),
        "bounds_val": bound_counts(list(val_rows)),
        "sources_train": dict(Counter(r.source or "?" for r in train_rows)),
        "sources_val": dict(Counter(r.source or "?" for r in val_rows)),
        "patterns": dict(
            Counter(
                (r.get("_meta") or {}).get("pattern", "?")
                for r in all_rows
                if isinstance(r.get("_meta"), dict)
            )
        ),
        "max_abs_offset_h": MAX_ABS_OFFSET_H,
        "min_conf": MIN_CONF_KEEP,
    }
    return list(train_rows), list(val_rows), report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build quality time train/val JSONL")
    parser.add_argument("--bootstrap", type=Path, default=DEFAULT_BOOTSTRAP)
    parser.add_argument("--chat", type=Path, action="append", default=None)
    parser.add_argument("--synthetic-n", type=int, default=1000)
    parser.add_argument("--neither-ratio", type=float, default=0.28)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=33)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    chats = args.chat if args.chat else DEFAULT_CHATS
    train_rows, val_rows, report = build(
        bootstrap_path=args.bootstrap,
        chat_paths=chats,
        synthetic_n=args.synthetic_n,
        neither_ratio=args.neither_ratio,
        val_ratio=args.val_ratio,
        seed=args.seed,
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.dry_run:
        print("dry-run: files not written")
        return

    DATA.mkdir(parents=True, exist_ok=True)
    write_jsonl(DATA / "train.jsonl", train_rows)
    write_jsonl(DATA / "val.jsonl", val_rows)
    (DATA / "label_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(train_rows)} -> {DATA / 'train.jsonl'}")
    print(f"Wrote {len(val_rows)} -> {DATA / 'val.jsonl'}")
    print(f"Report -> {DATA / 'label_report.json'}")


if __name__ == "__main__":
    main()
