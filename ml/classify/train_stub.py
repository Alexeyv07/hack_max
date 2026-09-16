"""Заготовка обучения importance-классификатора (НЕ часть runtime / src).

Запуск из корня репо:
  python ml/classify/train_stub.py

Сюда же позже: датасет в ml/classify/data/, чекпоинт в checkpoints/.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CHECKPOINTS = HERE / "checkpoints"


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    print("KAN-13 classify train stub")
    print(f"  data dir:        {DATA}")
    print(f"  checkpoints dir: {CHECKPOINTS}")
    print("Пока используется heuristic classify в src/parser_common.")
    print("Сюда положите labeled CSV/JSONL и дообучите tiny encoder на 3060.")


if __name__ == "__main__":
    main()
