"""Синтетика для smoke-train. Пишет в data/bootstrap.jsonl, train.jsonl не трогает.

Запуск из корня репо:
  python ml/classify/bootstrap_data.py
  python ml/classify/bootstrap_data.py --merge-into-train   # только append новых текстов
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "bootstrap.jsonl"
TRAIN = DATA / "train.jsonl"

# (шаблон, importance, disaster_flag) — флаги независимы
_DISASTER: list[tuple[str, int, bool]] = [
    ("В районе {place} землетрясение, объявлена эвакуация", 1, True),
    ("Катастрофа на {place}: взрыв и угроза обрушения", 1, True),
    ("Чрезвычайная ситуация: теракт возле {place}", 1, True),
    ("Цунами-предупреждение для зоны {place}", 1, True),
    ("Ядерная тревога, эвакуация жителей {place}", 1, True),
    ("Химическая авария у {place}, радиационный контроль", 1, True),
    ("Прорыв дамбы у {place}, идёт эвакуация", 1, True),
    ("Утечка хлора на объекте у {place}, людям не выходить", 1, True),
    ("Обрушение жилого дома на {place}, под завалами могут быть люди", 1, True),
    ("Режим ЧС введён в районе {place} после взрыва", 1, True),
    ("Захват заложников возле {place}, квартал оцеплен", 1, True),
    ("Крупный лесной пожар подходит к {place}, эвакуация", 1, True),
]

# важное ЖКХ / муниципалка — не ЧС, не срочная опасность
_IMPORTANT: list[tuple[str, int, bool]] = [
    ("Отключили воду на {place} до вечера", 2, False),
    ("Отключили свет на {place}", 2, False),
    ("Отключение электричества в районе {place}", 2, False),
    ("Прорыв трубы на {place}, без горячей воды (затопление остановлено)", 2, False),
    ("Авария теплосети: без отопления на {place}", 2, False),
    ("Отключили газ на {place}", 2, False),
    ("Ремонт теплосети на {place}", 2, False),
    ("Канализационный засор на {place}, сантехникой пользоваться нельзя", 2, False),
    ("Плановые работы на сетях: без воды на {place} с 9 до 17", 2, False),
    ("Не будет газа на {place} завтра с 8 до 12 из-за работ", 2, False),
    ("Без отопления на {place} после аварии на теплотрассе", 2, False),
    ("Перекрыли дорогу у {place} из-за ремонта коллектора", 2, False),
    ("Горячая вода отключена на {place} до конца недели", 2, False),
    ("Лифт не работает на {place}, кабина пустая", 2, False),
    ("Не работает домофон на {place}", 2, False),
    ("Завтра проверка газа на {place}, нужен доступ", 2, False),
]

# срочная локальная опасность — importance=1, не городская ЧС
_CRITICAL_NON_DISASTER: list[tuple[str, int, bool]] = [
    ("Пожар в подвале дома на {place}, сильное задымление", 1, False),
    ("Пожар в квартире на {place}, один подъезд задымлён", 1, False),
    ("Сильный запах газа в подъезде на {place}", 1, False),
    ("Утечка газа возле {place}, вызовите аварийную службу", 1, False),
    ("Прорвало стояк на {place}, вода сейчас заливает квартиры", 1, False),
    ("В лифте на {place} застряли люди, нужна помощь", 1, False),
    ("Во дворе {place} человек угрожает ножом", 1, False),
]

_TRIVIA: list[tuple[str, int, bool]] = [
    ("Пропала серая кошка возле {place}, отзовитесь", 3, False),
    ("Продаю диван, самовывоз с {place}", 3, False),
    ("Кто-нибудь видел курьера на {place}?", 3, False),
    ("Вечером концерт во дворе {place}", 3, False),
    ("Ищу соседа с дрелью на {place}", 3, False),
    ("Красивый закат над {place}", 3, False),
    ("Открылась новая кофейня на {place}", 3, False),
    ("Сдаю парковочное место у {place}", 3, False),
    ("Где на {place} ближайшая аптека?", 3, False),
    ("Кто играет в волейбол у {place} по вечерам?", 3, False),
    ("Отдам бесплатно рассаду, забирать на {place}", 3, False),
    ("Соседи, не шумите после 23:00 на {place}", 3, False),
]

_PLACES = [
    "Лесной",
    "улице Ленина",
    "Северном районе",
    "доме 10",
    "площади Победы",
    "микрорайоне Солнечный",
    "набережной",
    "переулке Садовом",
    "улице Гагарина",
    "ЖК Рассвет",
    "посёлке Заречье",
    "районе Южный",
]

_PARAPHRASE_PREFIX = (
    "",
    "Срочно: ",
    "Соседи, ",
    "Внимание! ",
    "Информация: ",
)


def _expand(
    templates: list[tuple[str, int, bool]],
    rng: random.Random,
    *,
    with_prefix: bool,
) -> list[dict]:
    rows: list[dict] = []
    for tmpl, importance, disaster in templates:
        for place in _PLACES:
            text = tmpl.format(place=place)
            if with_prefix:
                prefix = rng.choice(_PARAPHRASE_PREFIX)
                text = f"{prefix}{text}" if prefix else text
            rows.append(
                {
                    "text": text,
                    "importance": importance,
                    "disaster_flag": disaster,
                    "source": "synthetic",
                }
            )
    return rows


def build_rows(seed: int = 13) -> list[dict]:
    rng = random.Random(seed)
    rows = (
        _expand(_DISASTER, rng, with_prefix=True)
        + _expand(_IMPORTANT, rng, with_prefix=True)
        + _expand(_CRITICAL_NON_DISASTER, rng, with_prefix=True)
        + _expand(_TRIVIA, rng, with_prefix=False)
    )
    rng.shuffle(rows)
    # убрать точные дубли текста
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
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


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
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            existing_texts.add(key)
            added += 1
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description="Синтетика classify → bootstrap.jsonl")
    parser.add_argument(
        "--merge-into-train",
        action="store_true",
        help="Append только новых текстов в train.jsonl (без перезаписи)",
    )
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args()

    rows = build_rows(seed=args.seed)
    write_jsonl(OUT, rows)
    print(f"Wrote {len(rows)} rows -> {OUT}")

    if args.merge_into_train:
        n = merge_new_into_train(rows)
        print(f"Appended {n} new rows -> {TRAIN} (existing lines untouched)")
    else:
        print("train.jsonl not modified (use --merge-into-train to append missing texts)")


if __name__ == "__main__":
    main()
