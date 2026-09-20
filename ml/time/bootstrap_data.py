"""Синтетика time-window для smoke-train. Пишет data/bootstrap.jsonl, train.jsonl не трогает.

Запуск из корня репо:
  python ml/time/bootstrap_data.py
  python ml/time/bootstrap_data.py --merge-into-train   # только append новых текстов
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "bootstrap.jsonl"
TRAIN = DATA / "train.jsonl"

_MSK = timezone(timedelta(hours=3))

# (шаблон с {place}/{from_d}/{to_d}/{from_t}/{to_t}, kind)
# kind: both | from_only | to_only | neither
_MC_TEMPLATES: list[tuple[str, str]] = [
    (
        "Плановое отключение горячей воды на {place} с {from_d} {from_t} по {to_d} {to_t}",
        "both",
    ),
    (
        "Отключение ХВС по адресу {place}: {from_d} с {from_t} до {to_d} {to_t}",
        "both",
    ),
    (
        "Ремонт теплосети на {place}. Работы с {from_d} по {to_d}",
        "both",
    ),
    (
        "Без отопления на {place} с {from_d} {from_t} до устранения аварии",
        "from_only",
    ),
    (
        "С {from_d} на {place} начнут промывку сетей",
        "from_only",
    ),
    (
        "Горячую воду на {place} вернут до {to_d} {to_t}",
        "to_only",
    ),
    (
        "Ограничения на {place} действуют до {to_d}",
        "to_only",
    ),
    (
        "Аварийная бригада выехала на {place}, сроки уточняются",
        "neither",
    ),
    (
        "Информируем жителей {place} о проведении диагностики сетей",
        "neither",
    ),
]

_NEWS_TEMPLATES: list[tuple[str, str]] = [
    (
        "Перекрытие движения у {place} с {from_d} {from_t} по {to_d} {to_t}",
        "both",
    ),
    (
        "Ярмарка у {place} пройдёт {from_d} с {from_t} до {to_t}",
        "both",
    ),
    (
        "С {from_d} у {place} стартует ремонт дороги",
        "from_only",
    ),
    (
        "Ограничения у {place} снимут до {to_d}",
        "to_only",
    ),
    (
        "В районе {place} зафиксировали инцидент, подробности уточняются",
        "neither",
    ),
    (
        "Городские службы проверяют коммуникации возле {place}",
        "neither",
    ),
]

_PLACES = [
    "ул. Ленина, д. 10",
    "Лесной проспект",
    "ЖК Рассвет",
    "районе Нагатино",
    "улице Гагарина",
    "микрорайоне Солнечный",
    "набережной",
    "пер. Садовый",
]

_PREFIXES = ("", "Внимание! ", "Уважаемые жители, ", "Информация: ")


def _fmt_d(dt: datetime) -> str:
    return f"{dt.day:02d}.{dt.month:02d}.{dt.year}"


def _fmt_t(dt: datetime) -> str:
    return f"{dt.hour:02d}:{dt.minute:02d}"


def _make_window(
    rng: random.Random,
    reference: datetime,
    kind: str,
) -> tuple[datetime | None, datetime | None]:
    if kind == "neither":
        return None, None
    start_offset_h = rng.choice([6, 12, 24, 36, 48, 72, -6, 0])
    duration_h = rng.choice([6, 12, 24, 48, 72, 120])
    active_from = reference + timedelta(hours=start_offset_h)
    active_to = active_from + timedelta(hours=duration_h)
    # выровнять минуты к :00 / :30 для читаемых шаблонов
    active_from = active_from.replace(minute=rng.choice([0, 30]), second=0, microsecond=0)
    active_to = active_to.replace(minute=rng.choice([0, 30]), second=0, microsecond=0)
    if active_to <= active_from:
        active_to = active_from + timedelta(hours=6)
    if kind == "from_only":
        return active_from, None
    if kind == "to_only":
        return None, active_to
    return active_from, active_to


def _fill_template(
    tmpl: str,
    *,
    place: str,
    active_from: datetime | None,
    active_to: datetime | None,
    reference: datetime,
) -> str:
    # для шаблонов без одного bound подставляем reference-окрестность в текст
    from_dt = active_from or (reference + timedelta(days=1))
    to_dt = active_to or (from_dt + timedelta(days=1))
    return tmpl.format(
        place=place,
        from_d=_fmt_d(from_dt),
        to_d=_fmt_d(to_dt),
        from_t=_fmt_t(from_dt),
        to_t=_fmt_t(to_dt),
    )


def build_rows(seed: int = 19, *, n_per_template: int = 4) -> list[dict]:
    rng = random.Random(seed)
    base = datetime(2026, 3, 10, 12, 0, tzinfo=_MSK)
    rows: list[dict] = []

    for source, templates in (("mc", _MC_TEMPLATES), ("news", _NEWS_TEMPLATES)):
        for tmpl, kind in templates:
            for _ in range(n_per_template):
                place = rng.choice(_PLACES)
                ref = base + timedelta(
                    days=rng.randint(0, 20),
                    hours=rng.choice([8, 10, 12, 15, 18]),
                )
                active_from, active_to = _make_window(rng, ref, kind)
                text = _fill_template(
                    tmpl,
                    place=place,
                    active_from=active_from,
                    active_to=active_to,
                    reference=ref,
                )
                prefix = rng.choice(_PREFIXES)
                if prefix:
                    text = f"{prefix}{text}"
                rows.append(
                    {
                        "text": text,
                        "active_from": active_from.isoformat() if active_from else None,
                        "active_to": active_to.isoformat() if active_to else None,
                        "reference": ref.isoformat(),
                        "source": "synthetic",
                        "outlet": source,
                    }
                )

    rng.shuffle(rows)
    seen: set[str] = set()
    unique: list[dict] = []
    for row in rows:
        key = row["text"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            # outlet — служебное поле синтетики; в train-формат не обязательно
            payload = {
                "text": row["text"],
                "active_from": row["active_from"],
                "active_to": row["active_to"],
                "reference": row["reference"],
                "source": row.get("outlet") or row.get("source") or "synthetic",
            }
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def merge_new_into_train(synthetic: list[dict]) -> int:
    """Дописать в train.jsonl только тексты, которых ещё нет. Существующие строки не меняет."""
    existing_texts: set[str] = set()
    if TRAIN.is_file():
        for line in TRAIN.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            existing_texts.add(json.loads(line)["text"].strip().lower())

    added = 0
    with TRAIN.open("a", encoding="utf-8") as fh:
        for row in synthetic:
            key = row["text"].strip().lower()
            if key in existing_texts:
                continue
            payload = {
                "text": row["text"],
                "active_from": row["active_from"],
                "active_to": row["active_to"],
                "reference": row["reference"],
                "source": row.get("outlet") or row.get("source") or "synthetic",
            }
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
            existing_texts.add(key)
            added += 1
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description="Синтетика time → bootstrap.jsonl")
    parser.add_argument(
        "--merge-into-train",
        action="store_true",
        help="Append только новых текстов в train.jsonl (без перезаписи)",
    )
    parser.add_argument("--seed", type=int, default=19)
    parser.add_argument("--n-per-template", type=int, default=4)
    args = parser.parse_args()

    rows = build_rows(seed=args.seed, n_per_template=args.n_per_template)
    write_jsonl(OUT, rows)
    print(f"Wrote {len(rows)} rows -> {OUT}")

    if args.merge_into_train:
        n = merge_new_into_train(rows)
        print(f"Appended {n} new rows -> {TRAIN} (existing lines untouched)")
    else:
        print("train.jsonl not modified (use --merge-into-train to append missing texts)")


if __name__ == "__main__":
    main()
