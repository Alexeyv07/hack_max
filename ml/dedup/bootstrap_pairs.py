"""Синтетические пары для smoke eval порогов. Не трогает pairs.jsonl.

Запуск:
  python ml/dedup/bootstrap_pairs.py
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "bootstrap_pairs.jsonl"
PAIRS = DATA / "pairs.jsonl"

_PLACES = [
    "ул. Ленина",
    "Лесном проспекте",
    "ЖК Рассвет",
    "районе Нагатино",
    "ул. Гагарина",
]

# (text_a, text_b, label)
_SEED_PAIRS: list[tuple[str, str, str]] = [
    (
        "Отключили горячую воду на {place} до вечера",
        "На {place} нет ГВС до 18:00",
        "duplicate",
    ),
    (
        "Прорыв трубы на {place}, без холодной воды",
        "Авария ХВС: {place} без воды",
        "duplicate",
    ),
    (
        "Перекрыли дорогу у {place} из-за ремонта",
        "Движение ограничено возле {place}: идёт ремонт коллектора",
        "duplicate",
    ),
    (
        "Отключение отопления на {place} с утра",
        "На {place} вернули отопление, работы завершены",
        "update",
    ),
    (
        "Без света на {place} до 16:00",
        "Срок отключения на {place} продлили до 20:00",
        "update",
    ),
    (
        "Пожар в подвале на {place}",
        "Пожар на {place} локализован, пострадавших нет",
        "update",
    ),
    (
        "Отключили воду на {place}",
        "Концерт во дворе на {place}",
        "unrelated",
    ),
    (
        "Прорыв трубы на {place}",
        "Ярмарка выходного дня у {place}",
        "unrelated",
    ),
    (
        "Авария теплосети на {place}",
        "Пропала серая кошка возле {place}",
        "unrelated",
    ),
    (
        "Отключение газа на {place} до обеда",
        "Перекрытие движения в другом районе из-за съёмок",
        "unrelated",
    ),
]

_PARAPHRASE_B = {
    "duplicate": (
        "Соседи сообщают: {base}",
        "Информация: {base}",
        "{base}. Перепост.",
    ),
    "update": (
        "Обновление: {base}",
        "Уточнение по ситуации: {base}",
    ),
    "unrelated": ("{base}",),
}


def build_rows(seed: int = 19) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []
    for text_a_tmpl, text_b_tmpl, label in _SEED_PAIRS:
        for place in _PLACES:
            a = text_a_tmpl.format(place=place)
            b = text_b_tmpl.format(place=place)
            rows.append(
                {
                    "text_a": a,
                    "text_b": b,
                    "label": label,
                    "source": "synthetic",
                }
            )
            # лёгкий парафраз b
            for wrap in _PARAPHRASE_B[label]:
                b2 = wrap.format(base=b)
                if b2 == b:
                    continue
                rows.append(
                    {
                        "text_a": a,
                        "text_b": b2,
                        "label": label,
                        "source": "synthetic",
                    }
                )

    # hard-ish unrelated: одна тема, разные места
    for i, place_a in enumerate(_PLACES):
        place_b = _PLACES[(i + 1) % len(_PLACES)]
        rows.append(
            {
                "text_a": f"Отключили горячую воду на {place_a} до вечера",
                "text_b": f"Отключили горячую воду на {place_b} до вечера",
                "label": "unrelated",
                "source": "synthetic",
            }
        )

    rng.shuffle(rows)
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict] = []
    for row in rows:
        key = (
            row["text_a"].strip().lower(),
            row["text_b"].strip().lower(),
            row["label"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Синтетика dedup pairs → bootstrap_pairs.jsonl")
    parser.add_argument("--seed", type=int, default=19)
    args = parser.parse_args()

    rows = build_rows(seed=args.seed)
    write_jsonl(OUT, rows)
    print(f"Wrote {len(rows)} pairs -> {OUT}")
    if PAIRS.is_file():
        print(f"Note: {PAIRS.name} exists and was NOT modified")
    else:
        print(f"{PAIRS.name} not modified (user-supplied; create manually or copy bootstrap)")


if __name__ == "__main__":
    main()
