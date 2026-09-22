"""Сборка качественного classify-датасета по критериям категорий.

Источники:
  - src/parser_common/data/bootstrap_events.jsonl.gz
  - экспорты домовых чатов MAX
  - curated gold из критериев (пограничные кейсы)
  - синтетика, согласованная с критериями

Запуск:
  python ml/classify/build_train_from_sources.py
  python ml/classify/build_train_from_sources.py --dry-run
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = HERE / "data"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from criteria_label import LabelDecision, label_text  # noqa: E402
from dataset_io import ClassifyExample, class_counts, write_jsonl  # noqa: E402

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

MIN_CONF = 0.72
MAX_TEXT = 900


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:MAX_TEXT]


def _row(
    text: str,
    importance: int,
    disaster_flag: bool,
    source: str,
    *,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": _norm_text(text),
        "importance": importance,
        "disaster_flag": disaster_flag,
        "source": source,
    }
    if meta:
        payload["_meta"] = meta
    return payload


def _from_decision(text: str, dec: LabelDecision, source: str) -> dict[str, Any] | None:
    if dec.skip or dec.confidence < MIN_CONF:
        return None
    return _row(
        text,
        dec.importance,
        dec.disaster_flag,
        source,
        meta={"reason": dec.reason, "confidence": dec.confidence},
    )


# ---------------------------------------------------------------------------
# Curated gold (критерии §3–6)
# ---------------------------------------------------------------------------


def curated_gold() -> list[dict[str, Any]]:
    """Эталон из инструкции: пограничные + типовые сценарии."""
    gold: list[tuple[str, int, bool]] = [
        # §6 пограничные
        ("Завтра отключат воду до вечера", 2, False),
        ("Прорвало стояк, вода сейчас заливает квартиры", 1, False),
        ("Трубу перекрыли, затопление остановлено, воды пока нет", 2, False),
        ("Вчера был пожар, полностью потушен, ограничений нет", 3, False),
        ("После пожара запрещён вход в секцию, организована эвакуация", 1, False),
        ("После пожара ремонтируют лифт, он временно не работает", 2, False),
        ("Во дворе человек размахивает ножом и угрожает", 1, False),
        ("Рабочий режет упаковку ножом", 3, False),
        ("Соседи громко спорят о парковке", 3, False),
        ("Во дворе избивают человека", 1, False),
        ("Лифт не работает, кабина пустая", 2, False),
        ("В лифте застряли люди, нужна помощь", 1, False),
        ("Пропал кот", 3, False),
        ("Собака сейчас бросается на детей", 1, False),
        ("Потерял ключ от квартиры", 3, False),
        ("Общий замок сломан, входная дверь не закрывается", 2, False),
        ("Прямо сейчас взламывают дверь квартиры", 1, False),
        ("Завтра учебная проверка сирен", 2, False),
        ("Сейчас объявлена эвакуация из-за угрозы", 1, True),
        ("Отчёт о вчерашних учениях", 3, False),
        ("В Челябинской области отменён режим «Ракетная опасность»", 2, False),
        (
            "Внимание! отключении услуги ГВС с 23.07.2026 10:00:00. "
            "Планируемое время включения 27.07.2026 18:00:00",
            2,
            False,
        ),
        (
            "Горького 32 завтра в 8.15 приедет трактор для уборки снега. Просьба убрать машины.",
            2,
            False,
        ),
        ("Краб с ножом напал на жителя Флориды — вирусное видео", 3, False),
        ("МИД осудил теракты против избирательных комиссий", 3, False),
        # §3 срочная опасность
        ("В подъезде сильное задымление, источник неизвестен", 1, False),
        ("Житель сообщает о запахе газа в доме", 1, False),
        ("Искрит и дымится электрощит в подъезде", 1, False),
        ("Оборванный электрический провод лежит на дорожке у дома", 1, False),
        ("Из-за аварии человек заперт в опасном помещении, не может выбраться", 1, False),
        ("Подтверждён действующий поиск пропавшего маленького ребёнка во дворе", 1, False),
        ("С фасада прямо сейчас падают элементы на проход", 1, False),
        ("На проходе обнаружен открытый глубокий колодец без ограждения", 1, False),
        ("В квартире рядом с нами идёт пожар, дым в коридоре", 1, False),
        # §4 важно
        ("Плановое отключение горячей воды с понедельника по среду", 2, False),
        ("Водоснабжение восстановлено после аварии", 2, False),
        ("Не работает домофон на входной двери", 2, False),
        ("Не работает освещение подъезда", 2, False),
        ("Канализация не работает, пользоваться сантехникой нельзя", 2, False),
        ("Завтра проверка газового оборудования, требуется доступ в квартиру", 2, False),
        ("Ремонт дороги, перекрыт въезд во двор", 2, False),
        ("Перед уборкой снега трактором необходимо переставить машины", 2, False),
        ("Объявлено собрание собственников в субботу в 18:00", 2, False),
        ("Порывы ветра до 20 м/с ожидаются днём, уберите вещи с балконов", 2, False),
        ("Отключение ГВС с 23.07 10:00, включение 27.07 18:00", 2, False),
        # §5 информационное
        ("Продам диван, самовывоз", 3, False),
        ("Кто может одолжить дрель на вечер?", 3, False),
        ("Приглашение на дворовой концерт в субботу", 3, False),
        ("Открылась кофейня на первом этаже, скидка 10%", 3, False),
        ("Поздравляем Лену с днём рождения!", 3, False),
        ("Общая статья о правилах пожарной безопасности без локальной угрозы", 3, False),
        ("Новость о приговоре по делу двухлетней давности", 3, False),
        ("Когда-нибудь благоустроят двор, сроков нет", 3, False),
        # ЧС (disaster)
        ("В районе землетрясение, объявлена эвакуация", 1, True),
        ("Утечка хлора на объекте, людям не выходить на улицу", 1, True),
        ("Режим ЧС введён после взрыва на складе", 1, True),
        ("На территории области введён режим ракетной опасности", 1, True),
    ]
    return [
        _row(t, imp, dis, "curated", meta={"reason": "criteria_gold", "confidence": 1.0})
        for t, imp, dis in gold
    ]


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
            if body and title and title.lower() in body.lower():
                text = body
            elif title and body:
                text = f"{title}. {body}"
            else:
                text = title or body
            text = _norm_text(text)
            if len(text) < 20:
                continue
            rows.append(
                {
                    "text": text,
                    "source": str(raw.get("source") or "news"),
                    "old_importance": raw.get("importance"),
                    "old_disaster": raw.get("disaster_flag"),
                }
            )
    return rows


def load_chat_messages(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for msg in raw.get("messages") or []:
        if msg.get("is_service") or msg.get("type") == "system":
            continue
        text = (msg.get("body_text") or msg.get("text") or msg.get("display_text") or "").strip()
        text = _norm_text(text)
        if len(text) < 15:
            continue
        # отсечь явный шум чата без информативности
        if re.fullmatch(r"[+\d\s￼]+", text):
            continue
        out.append({"text": text, "source": "chat"})
    return out


def label_items(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    labeled: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for item in items:
        dec = label_text(item["text"])
        row = _from_decision(item["text"], dec, item["source"])
        if row is None:
            skipped[dec.reason] += 1
            continue
        labeled.append(row)
    return labeled, skipped


# ---------------------------------------------------------------------------
# Synthetic (согласовано с критериями)
# ---------------------------------------------------------------------------


def build_synthetic(n: int = 800, seed: int = 27) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    places = [
        "ул. Ленина",
        "пр. Комсомольский, 30",
        "ул. Сулимова, 47А",
        "ул. Горького, 32",
        "ЖК Рассвет",
        "районе Нагатино",
    ]
    templates: list[tuple[str, int, bool]] = [
        # 1
        ("В подъезде на {place} сильное задымление", 1, False),
        ("Запах газа в доме на {place}, вызывайте аварийку", 1, False),
        ("Пожар в квартире на {place}, дым идёт в коридор", 1, False),
        ("Прорвало стояк на {place}, вода заливает квартиры", 1, False),
        ("В лифте на {place} застряли люди, нужна помощь", 1, False),
        ("Во дворе {place} человек угрожает ножом", 1, False),
        ("Собака на {place} бросается на детей", 1, False),
        ("Объявлена эвакуация жителей {place} из-за угрозы", 1, True),
        ("Землетрясение у {place}, режим ЧС", 1, True),
        ("Утечка хлора возле {place}, не выходите на улицу", 1, True),
        # 2
        ("Отключили воду на {place} до вечера", 2, False),
        ("Отключение ГВС на {place} с 10:00 до 18:00", 2, False),
        ("Лифт не работает на {place}, кабина пустая", 2, False),
        ("Перекрыт въезд во двор на {place} из-за ремонта", 2, False),
        ("Завтра на {place} проверка газа, нужен доступ", 2, False),
        ("Не работает домофон на {place}", 2, False),
        ("Опрессовка на {place}: без горячей воды две недели", 2, False),
        ("Трактор завтра в 8:15 чистит снег на {place}, уберите машины", 2, False),
        ("Водоснабжение на {place} восстановлено", 2, False),
        ("Собрание собственников на {place} в субботу", 2, False),
        ("Штормовое предупреждение для {place}: сильный ветер днём", 2, False),
        ("Трубу перекрыли на {place}, затопление остановлено, воды пока нет", 2, False),
        # 3
        ("Пропала серая кошка возле {place}", 3, False),
        ("Продам диван, самовывоз с {place}", 3, False),
        ("Кто одолжит дрель на {place}?", 3, False),
        ("Концерт во дворе {place} в субботу", 3, False),
        ("Открылась кофейня у {place}", 3, False),
        ("Поздравляем соседей на {place} с праздником", 3, False),
        ("Вчера на {place} был пожар, полностью потушен, ограничений нет", 3, False),
        ("Счета за ЖКУ по {place} доступны в приложении", 3, False),
        ("Общая памятка по безопасности для жителей {place}", 3, False),
        ("Рабочий на {place} режет упаковку ножом", 3, False),
    ]
    # веса: больше 2 и 3, класс 1 не забивать
    weights = []
    for _, imp, _ in templates:
        weights.append({1: 2, 2: 4, 3: 4}[imp])

    rows: list[dict[str, Any]] = []
    prefixes = ("", "Внимание! ", "Соседи, ", "Срочно: ", "Информация: ")
    for _ in range(n):
        tmpl, imp, dis = rng.choices(templates, weights=weights, k=1)[0]
        place = rng.choice(places)
        text = rng.choice(prefixes) + tmpl.format(place=place)
        rows.append(_row(text, imp, dis, "synthetic", meta={"reason": "synth", "confidence": 1.0}))
    return rows


# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = row["text"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _to_example(row: dict[str, Any]) -> ClassifyExample:
    return ClassifyExample(
        text=row["text"],
        importance=int(row["importance"]),
        disaster_flag=bool(row["disaster_flag"]),
        source=row.get("source"),
    )


def _balance(
    rows: list[dict[str, Any]],
    *,
    max_per_class: dict[int, int],
    rng: random.Random,
) -> list[dict[str, Any]]:
    by: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: []}
    for r in rows:
        by[int(r["importance"])].append(r)
    out: list[dict[str, Any]] = []
    for cls, bucket in by.items():
        rng.shuffle(bucket)
        # приоритет: curated > chat > mc > news > synthetic
        priority = {"curated": 0, "chat": 1, "mc": 2, "news": 3, "synthetic": 4}
        bucket.sort(key=lambda r: priority.get(str(r.get("source")), 9))
        out.extend(bucket[: max_per_class.get(cls, len(bucket))])
    rng.shuffle(out)
    return out


def build(
    *,
    bootstrap_path: Path,
    chat_paths: list[Path],
    synthetic_n: int,
    val_ratio: float,
    seed: int,
    max_class3: int,
    max_class2: int,
    max_class1: int,
) -> tuple[list[ClassifyExample], list[ClassifyExample], dict[str, Any]]:
    rng = random.Random(seed)

    bootstrap_items = load_bootstrap_events(bootstrap_path) if bootstrap_path.is_file() else []
    chat_items: list[dict[str, Any]] = []
    for p in chat_paths:
        if p.is_file():
            chat_items.extend(load_chat_messages(p))

    gold = curated_gold()
    boot_lab, boot_skip = label_items(bootstrap_items)
    chat_lab, chat_skip = label_items(chat_items)
    synth = build_synthetic(n=synthetic_n, seed=seed)

    all_rows = _dedupe(gold + chat_lab + boot_lab + synth)
    all_rows = _balance(
        all_rows,
        max_per_class={1: max_class1, 2: max_class2, 3: max_class3},
        rng=rng,
    )

    examples = [_to_example(r) for r in all_rows]

    from sklearn.model_selection import train_test_split

    strata = [e.importance for e in examples]
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
            "gold": len(gold),
            "bootstrap": len(boot_lab),
            "chat": len(chat_lab),
            "synthetic": len(synth),
            "after_balance": len(examples),
            "train": len(train_rows),
            "val": len(val_rows),
        },
        "skipped_bootstrap": dict(boot_skip.most_common(15)),
        "skipped_chat": dict(chat_skip.most_common(15)),
        "class_train": class_counts(list(train_rows)),
        "class_val": class_counts(list(val_rows)),
        "disaster_train": sum(1 for r in train_rows if r.disaster_flag),
        "disaster_val": sum(1 for r in val_rows if r.disaster_flag),
        "sources_train": dict(Counter(r.source or "?" for r in train_rows)),
        "sources_val": dict(Counter(r.source or "?" for r in val_rows)),
        "reasons": dict(Counter((r.get("_meta") or {}).get("reason", "?") for r in all_rows)),
        "min_conf": MIN_CONF,
    }
    return list(train_rows), list(val_rows), report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build classify train/val from real sources")
    parser.add_argument("--bootstrap", type=Path, default=DEFAULT_BOOTSTRAP)
    parser.add_argument("--chat", type=Path, action="append", default=None)
    parser.add_argument("--synthetic-n", type=int, default=900)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=27)
    parser.add_argument("--max-class1", type=int, default=400)
    parser.add_argument("--max-class2", type=int, default=900)
    parser.add_argument("--max-class3", type=int, default=1100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    chats = args.chat if args.chat else DEFAULT_CHATS
    train_rows, val_rows, report = build(
        bootstrap_path=args.bootstrap,
        chat_paths=chats,
        synthetic_n=args.synthetic_n,
        val_ratio=args.val_ratio,
        seed=args.seed,
        max_class1=args.max_class1,
        max_class2=args.max_class2,
        max_class3=args.max_class3,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.dry_run:
        print("dry-run: files not written")
        return

    DATA.mkdir(parents=True, exist_ok=True)
    write_jsonl(DATA / "train.jsonl", train_rows)
    write_jsonl(DATA / "val.jsonl", val_rows)
    (DATA / "label_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # копия критериев рядом с данными (удобно при ревью)
    criteria_src = Path(r"C:\Users\iosh\Downloads\Telegram Desktop\Критерии_категорий_событий.txt")
    if criteria_src.is_file():
        (HERE / "criteria_categories.txt").write_text(
            criteria_src.read_text(encoding="utf-8"), encoding="utf-8"
        )

    print(f"Wrote {len(train_rows)} -> {DATA / 'train.jsonl'}")
    print(f"Wrote {len(val_rows)} -> {DATA / 'val.jsonl'}")
    print(f"Report -> {DATA / 'label_report.json'}")


if __name__ == "__main__":
    main()
