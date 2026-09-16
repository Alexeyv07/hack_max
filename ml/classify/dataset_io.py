"""Загрузка JSONL для classify (train / weak_label / evaluate)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ClassifyExample:
    text: str
    importance: int
    disaster_flag: bool
    source: str | None = None


def load_jsonl(path: Path) -> list[ClassifyExample]:
    rows: list[ClassifyExample] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: битый JSON") from exc
            text = str(raw.get("text") or "").strip()
            if not text:
                raise ValueError(f"{path}:{line_no}: пустой text")
            importance = int(raw["importance"])
            if importance not in (1, 2, 3):
                raise ValueError(f"{path}:{line_no}: importance должен быть 1|2|3")
            # disaster_flag независим от importance (не форсим 1↔true)
            disaster = bool(raw["disaster_flag"]) if "disaster_flag" in raw else False
            source = raw.get("source")
            rows.append(
                ClassifyExample(
                    text=text,
                    importance=importance,
                    disaster_flag=disaster,
                    source=str(source) if source is not None else None,
                )
            )
    if not rows:
        raise ValueError(f"Пустой датасет: {path}")
    return rows


def write_jsonl(path: Path, rows: list[ClassifyExample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            payload = {
                "text": row.text,
                "importance": row.importance,
                "disaster_flag": row.disaster_flag,
            }
            if row.source is not None:
                payload["source"] = row.source
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def label_to_id(importance: int) -> int:
    """importance 1|2|3 -> class id 0|1|2."""
    return importance - 1


def id_to_label(class_id: int) -> int:
    return class_id + 1


def class_counts(rows: list[ClassifyExample]) -> dict[int, int]:
    counts = {1: 0, 2: 0, 3: 0}
    for row in rows:
        counts[row.importance] += 1
    return counts
