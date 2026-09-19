"""Entrypoint контейнера бота: classify-веса, миграции, данные, затем polling."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic.config import main as alembic_main

from address.seed import ensure_addresses_seeded
from main import main as bot_main
from parser_common.seed import ensure_events_seeded

_ARTIFACTS = Path(__file__).resolve().parents[1] / "ml" / "classify" / "artifacts"
_ONNX = _ARTIFACTS / "importance_model.onnx"
_META = _ARTIFACTS / "importance_model.meta.json"
_TOKENIZER = _ARTIFACTS / "tokenizer"


def _check_classify_artifacts() -> None:
    missing = [p.name for p in (_ONNX, _META, _TOKENIZER) if not p.exists()]
    if missing:
        print(
            "WARN: classify artifacts missing "
            f"({', '.join(missing)} under {_ARTIFACTS}). "
            "Importance уйдёт в keyword-rules. "
            "Обучите модель: python ml/classify/train_torch.py "
            "и пересоберите/перемонтируйте artifacts.",
            file=sys.stderr,
            flush=True,
        )
        return
    size_mb = _ONNX.stat().st_size / (1024 * 1024)
    print(
        f"classify ONNX ok: {_ONNX.name} ({size_mb:.1f} MiB), tokenizer present",
        flush=True,
    )


def run() -> None:
    _check_classify_artifacts()
    print("Применяем миграции Alembic...", flush=True)
    alembic_main(argv=["upgrade", "head"])

    print("Проверяем справочник адресов...", flush=True)
    if ensure_addresses_seeded():
        print("Справочник адресов загружен", flush=True)
    else:
        print("Справочник адресов уже загружен", flush=True)

    print("Проверяем snapshot событий...", flush=True)
    if ensure_events_seeded():
        print("События из snapshot загружены", flush=True)
    else:
        print("Snapshot событий пропущен (нет файла или events уже не пуста)", flush=True)

    print("Запускаем бота...", flush=True)
    bot_main()


if __name__ == "__main__":
    try:
        run()
    except SystemExit:
        raise
    except Exception:
        print("Ошибка entrypoint бота", file=sys.stderr, flush=True)
        raise
