"""Интерактивная проверка importance-классификатора (ONNX + rules).

Запуск из корня репо (с установленным .[ml] и артефактами после train_torch)::

  set PYTHONPATH=src
  python scripts/classify_try.py

Одна строка — один запрос. Пустая строка / ``q`` / ``quit`` — выход.
Многострочный текст: набери ``:m``, затем строки, закончи одиночной ``.``
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parser_common.classify import (  # noqa: E402
    classify_by_rules,
    classify_importance,
    clear_rules_cache,
)
from parser_common.model_onnx import (  # noqa: E402
    DEFAULT_ONNX_PATH,
    predict_importance_onnx,
)


def _read_multiline() -> str:
    print("многострочный режим — конец: строка с одной точкой", flush=True)
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == ".":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _fmt_probs(probs: tuple[float, float, float] | None) -> str:
    if not probs:
        return "—"
    return f"p1={probs[0]:.3f}  p2={probs[1]:.3f}  p3={probs[2]:.3f}"


def _run_one(text: str, *, min_confidence: float) -> None:
    rules = classify_by_rules(text)
    onnx = predict_importance_onnx(text, min_confidence=0.0)
    final = classify_importance(text, min_confidence=min_confidence)

    print("---", flush=True)
    if onnx is None:
        print("ONNX:      недоступен (нет артефакта / deps)", flush=True)
    else:
        print(
            f"ONNX:      importance={onnx.importance}  "
            f"conf={onnx.confidence:.3f}  {_fmt_probs(onnx.probs)}",
            flush=True,
        )
        if onnx.confidence < min_confidence:
            print(
                f"           (ниже порога {min_confidence:.2f} → в каскаде не победит)",
                flush=True,
            )
    print(
        f"rules:     importance={rules.importance}  disaster={rules.disaster_flag}",
        flush=True,
    )
    print(
        f"cascade:   importance={final.importance}  "
        f"disaster={final.disaster_flag}  method={final.method}",
        flush=True,
    )
    print("---", flush=True)


def main() -> None:
    min_confidence = 0.45
    clear_rules_cache()

    onnx_ok = DEFAULT_ONNX_PATH.is_file()
    print("classify try — ONNX → rules", flush=True)
    print(f"artifact: {DEFAULT_ONNX_PATH}  ({'ok' if onnx_ok else 'MISSING'})", flush=True)
    print(f"min_confidence={min_confidence}  |  :m = multiline  |  q = quit", flush=True)
    print(flush=True)

    while True:
        try:
            raw = input("> ").rstrip("\n")
        except (EOFError, KeyboardInterrupt):
            print(flush=True)
            break

        cmd = raw.strip().lower()
        if not cmd or cmd in {"q", "quit", "exit"}:
            break
        if cmd == ":m":
            text = _read_multiline()
            if not text:
                continue
            _run_one(text, min_confidence=min_confidence)
            continue

        _run_one(raw.strip(), min_confidence=min_confidence)


if __name__ == "__main__":
    main()
