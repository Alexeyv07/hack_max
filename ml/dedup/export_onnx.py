"""Stub: экспорт embedding-encoder для dedup в ONNX.

Пока runtime может грузить HF/transformers mean-pool напрямую.
Когда понадобится ONNX в src — дописать по аналогии с ml/classify/export_onnx.py:

  inputs:  input_ids, attention_mask
  output:  embedding  (mean-pool + L2-norm, dim = hidden_size)

Запуск сейчас только документирует контракт:

  python ml/dedup/export_onnx.py --help
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def export_embedding_onnx(
    *,
    model_name: str,
    onnx_path: Path,
    tokenizer_dir: Path,
    max_length: int = 128,
) -> None:
    """Полный экспорт — TODO (нужен torch + onnxruntime в train-окружении)."""
    raise NotImplementedError(
        "Экспорт embedding ONNX ещё не реализован.\n"
        f"План: AutoModel({model_name}) → mean-pool → L2 → ONNX\n"
        f"цель: {onnx_path}, tokenizer → {tokenizer_dir}, max_length={max_length}\n"
        "См. ml/dedup/MODEL.md и ml/classify/export_onnx.py как образец."
    )


def write_contract_meta(path: Path, *, model_name: str, max_length: int) -> None:
    """Записать JSON-контракт будущего артефакта (без весов)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "format": "rubert_embedding_onnx_v1_planned",
        "status": "stub",
        "base_model": model_name,
        "max_length": max_length,
        "pooling": "mean",
        "normalize": "l2",
        "inputs": ["input_ids", "attention_mask"],
        "outputs": ["embedding"],
        "note": (
            "Реализовать export_embedding_onnx(); "
            "runtime dedup читает cosine пороги из config/thresholds.json"
        ),
    }
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Contract meta -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stub export для dedup embedding encoder (ONNX)")
    parser.add_argument(
        "--model-name",
        type=str,
        default="cointegrated/rubert-tiny2",
    )
    parser.add_argument(
        "--onnx",
        type=Path,
        default=HERE / "artifacts" / "embedding_model.onnx",
    )
    parser.add_argument(
        "--tokenizer-dir",
        type=Path,
        default=HERE / "artifacts" / "tokenizer",
    )
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument(
        "--write-contract-only",
        action="store_true",
        help="Записать embedding_model.meta.json без реального ONNX",
    )
    args = parser.parse_args()

    if args.write_contract_only:
        meta_path = args.onnx.with_suffix(".meta.json")
        write_contract_meta(
            meta_path,
            model_name=args.model_name,
            max_length=args.max_length,
        )
        return

    export_embedding_onnx(
        model_name=args.model_name,
        onnx_path=args.onnx,
        tokenizer_dir=args.tokenizer_dir,
        max_length=args.max_length,
    )


if __name__ == "__main__":
    main()
