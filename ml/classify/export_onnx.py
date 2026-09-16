"""Экспорт HF checkpoint -> ONNX (+ копирование tokenizer в artifacts)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from torch import nn

HERE = Path(__file__).resolve().parent


class _OnnxWrapper(nn.Module):
    def __init__(self, model: nn.Module) -> None:
        super().__init__()
        self.model = model

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        out = self.model(input_ids=input_ids, attention_mask=attention_mask)
        return out.logits


def export_onnx(
    checkpoint_dir: Path,
    onnx_path: Path,
    tokenizer_dir: Path,
    *,
    max_length: int = 128,
    opset: int = 14,
) -> None:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(checkpoint_dir)
    model = AutoModelForSequenceClassification.from_pretrained(checkpoint_dir)
    model.eval()
    wrapped = _OnnxWrapper(model)
    wrapped.eval()

    tokenizer_dir.mkdir(parents=True, exist_ok=True)
    tokenizer.save_pretrained(tokenizer_dir)

    dummy = tokenizer(
        "проверка экспорта onnx",
        return_tensors="pt",
        padding="max_length",
        truncation=True,
        max_length=max_length,
    )
    onnx_path.parent.mkdir(parents=True, exist_ok=True)

    torch.onnx.export(
        wrapped,
        (dummy["input_ids"], dummy["attention_mask"]),
        str(onnx_path),
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "logits": {0: "batch"},
        },
        opset_version=opset,
        do_constant_folding=True,
    )

    # HF id2label часто {"0": "LABEL_0"}; у нас в train задаём "1"/"2"/"3"
    id2label = {}
    for k, v in model.config.id2label.items():
        key = int(k)
        try:
            id2label[str(key)] = int(v)
        except (TypeError, ValueError):
            id2label[str(key)] = key + 1

    meta = {
        "format": "rubert_onnx_v1",
        "max_length": max_length,
        "id2label": id2label,
        "label2id": {str(k): int(v) for k, v in model.config.label2id.items()},
        "onnx": onnx_path.name,
        "tokenizer_dir": tokenizer_dir.name,
        "num_labels": int(model.config.num_labels),
        "base_model": getattr(model.config, "_name_or_path", ""),
    }
    meta_path = onnx_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ONNX -> {onnx_path}")
    print(f"Tokenizer -> {tokenizer_dir}")
    print(f"Meta -> {meta_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export classify checkpoint to ONNX")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=HERE / "checkpoints" / "rubert_importance" / "best",
    )
    parser.add_argument(
        "--onnx",
        type=Path,
        default=HERE / "artifacts" / "importance_model.onnx",
    )
    parser.add_argument(
        "--tokenizer-dir",
        type=Path,
        default=HERE / "artifacts" / "tokenizer",
    )
    parser.add_argument("--max-length", type=int, default=128)
    args = parser.parse_args()
    if not args.checkpoint.is_dir():
        raise SystemExit(f"Нет checkpoint: {args.checkpoint}")
    export_onnx(args.checkpoint, args.onnx, args.tokenizer_dir, max_length=args.max_length)


if __name__ == "__main__":
    main()
