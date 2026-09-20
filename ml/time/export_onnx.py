"""Экспорт time-window multi-head checkpoint → ONNX (+ tokenizer в artifacts)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import torch
from torch import nn

HERE = Path(__file__).resolve().parent


class _OnnxWrapper(nn.Module):
    """Четыре выхода: has_from_logit, has_to_logit, from_offset, to_offset."""

    def __init__(self, model: nn.Module) -> None:
        super().__init__()
        self.model = model

    def forward(
        self, input_ids: torch.Tensor, attention_mask: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        out = self.model(input_ids=input_ids, attention_mask=attention_mask)
        return (
            out["has_from_logit"],
            out["has_to_logit"],
            out["from_offset"],
            out["to_offset"],
        )


def _rebuild_model(base_model: str) -> nn.Module:
    from transformers import AutoConfig, AutoModel

    class TimeWindowMultiHead(nn.Module):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.config = AutoConfig.from_pretrained(name)
            self.encoder = AutoModel.from_pretrained(name)
            hidden = int(self.config.hidden_size)
            self.has_from_head = nn.Linear(hidden, 1)
            self.has_to_head = nn.Linear(hidden, 1)
            self.from_offset_head = nn.Linear(hidden, 1)
            self.to_offset_head = nn.Linear(hidden, 1)

        def forward(
            self,
            input_ids: torch.Tensor,
            attention_mask: torch.Tensor,
            **_: Any,
        ) -> dict[str, torch.Tensor]:
            enc = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
            cls = enc.last_hidden_state[:, 0]
            return {
                "has_from_logit": self.has_from_head(cls).squeeze(-1),
                "has_to_logit": self.has_to_head(cls).squeeze(-1),
                "from_offset": self.from_offset_head(cls).squeeze(-1),
                "to_offset": self.to_offset_head(cls).squeeze(-1),
            }

    return TimeWindowMultiHead(base_model)


def export_onnx(
    model: nn.Module | None,
    tokenizer: Any,
    onnx_path: Path,
    tokenizer_dir: Path,
    *,
    max_length: int = 160,
    opset: int = 14,
    base_model: str = "cointegrated/rubert-tiny2",
    checkpoint_dir: Path | None = None,
) -> None:
    if model is None:
        if checkpoint_dir is None:
            raise ValueError("нужен model или checkpoint_dir")
        meta_path = checkpoint_dir / "model_type.json"
        name = base_model
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            name = str(meta.get("base_model") or name)
        model = _rebuild_model(name)
        weights = checkpoint_dir / "pytorch_model.bin"
        state = torch.load(weights, map_location="cpu", weights_only=True)
        model.load_state_dict(state)

    model.eval()
    wrapped = _OnnxWrapper(model)
    wrapped.eval()

    tokenizer_dir.mkdir(parents=True, exist_ok=True)
    tokenizer.save_pretrained(tokenizer_dir)

    dummy = tokenizer(
        "проверка экспорта onnx: отключение воды с 12 по 14 марта",
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
        output_names=[
            "has_from_logit",
            "has_to_logit",
            "from_offset",
            "to_offset",
        ],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "has_from_logit": {0: "batch"},
            "has_to_logit": {0: "batch"},
            "from_offset": {0: "batch"},
            "to_offset": {0: "batch"},
        },
        opset_version=opset,
        do_constant_folding=True,
    )

    meta = {
        "format": "rubert_time_window_onnx_v1",
        "max_length": max_length,
        "offset_unit": "hours",
        "outputs": [
            "has_from_logit",
            "has_to_logit",
            "from_offset",
            "to_offset",
        ],
        "has_threshold": 0.5,
        "onnx": onnx_path.name,
        "tokenizer_dir": tokenizer_dir.name,
        "base_model": base_model,
        "note": "active_* = reference + timedelta(hours=offset) если sigmoid(has_*) >= threshold",
    }
    meta_path = onnx_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ONNX -> {onnx_path}")
    print(f"Tokenizer -> {tokenizer_dir}")
    print(f"Meta -> {meta_path}")


def main() -> None:
    from transformers import AutoTokenizer

    parser = argparse.ArgumentParser(description="Export time-window checkpoint to ONNX")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=HERE / "checkpoints" / "rubert_time" / "best",
    )
    parser.add_argument(
        "--onnx",
        type=Path,
        default=HERE / "artifacts" / "time_window_model.onnx",
    )
    parser.add_argument(
        "--tokenizer-dir",
        type=Path,
        default=HERE / "artifacts" / "tokenizer",
    )
    parser.add_argument("--max-length", type=int, default=160)
    parser.add_argument(
        "--base-model",
        type=str,
        default="cointegrated/rubert-tiny2",
    )
    args = parser.parse_args()
    if not args.checkpoint.is_dir():
        raise SystemExit(f"Нет checkpoint: {args.checkpoint}")
    tokenizer = AutoTokenizer.from_pretrained(args.checkpoint)
    export_onnx(
        None,
        tokenizer,
        args.onnx,
        args.tokenizer_dir,
        max_length=args.max_length,
        base_model=args.base_model,
        checkpoint_dir=args.checkpoint,
    )


if __name__ == "__main__":
    main()
