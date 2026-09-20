"""Экспорт rubert-tiny2 mean-pool encoder → ONNX для runtime dedup.

Артефакты (совпадают с src/ml_dedup/embed.py):
  ml/dedup/artifacts/embed_model.onnx
  ml/dedup/artifacts/embed_model.meta.json
  ml/dedup/artifacts/tokenizer/

Запуск (нужен torch + transformers):

  pip install torch --index-url https://download.pytorch.org/whl/cu124
  pip install -e ".[ml]"
  python ml/dedup/export_onnx.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from torch import nn

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = "cointegrated/rubert-tiny2"


class MeanPoolEmbedder(nn.Module):
    """HF AutoModel → mean-pool (mask) → L2-norm. Один выход: embedding."""

    def __init__(self, encoder: nn.Module) -> None:
        super().__init__()
        self.encoder = encoder

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        hidden = out.last_hidden_state
        mask = attention_mask.unsqueeze(-1).expand(hidden.size()).float()
        summed = (hidden * mask).sum(dim=1)
        counts = mask.sum(dim=1).clamp(min=1e-9)
        pooled = summed / counts
        return torch.nn.functional.normalize(pooled, p=2, dim=1)


def export_embedding_onnx(
    *,
    model_name: str,
    onnx_path: Path,
    tokenizer_dir: Path,
    max_length: int = 128,
    opset: int = 14,
) -> None:
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    encoder = AutoModel.from_pretrained(model_name)
    encoder.eval()
    model = MeanPoolEmbedder(encoder)
    model.eval()

    tokenizer_dir.mkdir(parents=True, exist_ok=True)
    tokenizer.save_pretrained(tokenizer_dir)

    dummy = tokenizer(
        "проверка экспорта onnx embedding для дедупа",
        return_tensors="pt",
        padding="max_length",
        truncation=True,
        max_length=max_length,
    )
    onnx_path.parent.mkdir(parents=True, exist_ok=True)

    with torch.no_grad():
        torch.onnx.export(
            model,
            (dummy["input_ids"], dummy["attention_mask"]),
            str(onnx_path),
            input_names=["input_ids", "attention_mask"],
            output_names=["embedding"],
            dynamic_axes={
                "input_ids": {0: "batch", 1: "seq"},
                "attention_mask": {0: "batch", 1: "seq"},
                "embedding": {0: "batch"},
            },
            opset_version=opset,
            do_constant_folding=True,
        )

    hidden = int(encoder.config.hidden_size)
    meta = {
        "format": "rubert_embedding_onnx_v1",
        "base_model": model_name,
        "max_length": max_length,
        "hidden_size": hidden,
        "pooling": "mean",
        "normalize": "l2",
        "inputs": ["input_ids", "attention_mask"],
        "outputs": ["embedding"],
        "onnx": onnx_path.name,
        "tokenizer_dir": tokenizer_dir.name,
    }
    meta_path = onnx_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"ONNX -> {onnx_path} ({onnx_path.stat().st_size / 1024 / 1024:.1f} MiB)")
    print(f"Tokenizer -> {tokenizer_dir}")
    print(f"Meta -> {meta_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export rubert-tiny2 mean-pool embeddings to ONNX (KAN-19)"
    )
    parser.add_argument("--model-name", type=str, default=DEFAULT_MODEL)
    parser.add_argument(
        "--onnx",
        type=Path,
        default=HERE / "artifacts" / "embed_model.onnx",
        help="путь должен совпадать с src/ml_dedup/embed.py DEFAULT_ONNX",
    )
    parser.add_argument(
        "--tokenizer-dir",
        type=Path,
        default=HERE / "artifacts" / "tokenizer",
    )
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--opset", type=int, default=14)
    args = parser.parse_args()

    export_embedding_onnx(
        model_name=args.model_name,
        onnx_path=args.onnx,
        tokenizer_dir=args.tokenizer_dir,
        max_length=args.max_length,
        opset=args.opset,
    )


if __name__ == "__main__":
    main()
