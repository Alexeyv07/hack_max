"""Weak-label сырых текстов через rules (для последующего ручного ревью).

  python ml/classify/weak_label.py --in raw.jsonl --out ml/classify/data/weak_chat.jsonl

Вход: JSONL с полем text (остальные поля копируются).
Выход: text + importance + disaster_flag + source=weak_rules + needs_review=true
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parser_common.classify import classify_by_rules  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Weak-label texts via keyword rules")
    parser.add_argument("--in", dest="inp", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    n = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.inp.open(encoding="utf-8") as fin, args.out.open("w", encoding="utf-8") as fout:
        for line_no, line in enumerate(fin, start=1):
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            text = str(raw.get("text") or "").strip()
            if not text:
                raise SystemExit(f"{args.inp}:{line_no}: пустой text")
            result = classify_by_rules(text)
            out = {
                **raw,
                "text": text,
                "importance": result.importance,
                "disaster_flag": result.disaster_flag,
                "source": raw.get("source") or "weak_rules",
                "needs_review": True,
            }
            fout.write(json.dumps(out, ensure_ascii=False) + "\n")
            n += 1
    print(f"Weak-labeled {n} rows -> {args.out}")
    print("Откройте файл и поправьте needs_review / importance перед train_torch.")


if __name__ == "__main__":
    main()
