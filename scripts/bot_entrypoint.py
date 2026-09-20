"""Entrypoint контейнера бота: ML-артефакты, миграции, seed, затем main."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic.config import main as alembic_main

from address.seed import ensure_addresses_seeded
from main import main as bot_main
from parser_common.seed import ensure_events_seeded

_ROOT = Path(__file__).resolve().parents[1]


def _warn_missing(label: str, paths: list[Path], hint: str) -> None:
    missing = [str(p.relative_to(_ROOT)) for p in paths if not p.exists()]
    if missing:
        print(
            f"WARN: {label} missing ({', '.join(missing)}). {hint}",
            file=sys.stderr,
            flush=True,
        )
        return
    print(f"{label}: ok", flush=True)


def _check_ml_artifacts() -> None:
    classify_dir = _ROOT / "ml" / "classify" / "artifacts"
    _warn_missing(
        "classify ONNX",
        [
            classify_dir / "importance_model.onnx",
            classify_dir / "importance_model.meta.json",
            classify_dir / "tokenizer",
        ],
        "Importance → keyword-rules. Обучите: python ml/classify/train_torch.py",
    )

    time_dir = _ROOT / "ml" / "time" / "artifacts"
    _warn_missing(
        "time-window ONNX",
        [
            time_dir / "time_window_model.onnx",
            time_dir / "time_window_model.meta.json",
            time_dir / "tokenizer",
        ],
        "active_from/to останутся null. Обучите: python ml/time/train_torch.py",
    )

    dedup_embed = _ROOT / "ml" / "dedup" / "artifacts" / "embed_model.onnx"
    if dedup_embed.is_file():
        print(f"dedup embed ONNX: ok ({dedup_embed.name})", flush=True)
    else:
        print(
            "WARN: dedup embed ONNX отсутствует — "
            "cosine через transformers/hash fallback. "
            "Пороги: python ml/dedup/eval_threshold.py",
            file=sys.stderr,
            flush=True,
        )


def run() -> None:
    _check_ml_artifacts()
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
