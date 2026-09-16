"""
ONNX-инференс fine-tuned rubert-tiny2 (3 класса importance).

Артефакты (train_torch.py / export_onnx.py):
  - ml/classify/artifacts/importance_model.onnx
  - ml/classify/artifacts/importance_model.meta.json
  - ml/classify/artifacts/tokenizer/

Optional deps: onnxruntime, transformers. Нет их / нет файлов → None
(выше по стеку сработают rules).

method: ``\"onnx\"``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from parser_common.text_features import softmax
from project.config import PROJECT_ROOT

DEFAULT_ONNX_PATH = PROJECT_ROOT / "ml" / "classify" / "artifacts" / "importance_model.onnx"
DEFAULT_META_PATH = DEFAULT_ONNX_PATH.with_suffix(".meta.json")
DEFAULT_TOKENIZER_DIR = PROJECT_ROOT / "ml" / "classify" / "artifacts" / "tokenizer"


@dataclass(frozen=True, slots=True)
class ModelPrediction:
    importance: int
    disaster_flag: bool
    confidence: float
    method: str  # "onnx"
    probs: tuple[float, float, float] | None = None  # p(class1), p(2), p(3)


@dataclass(frozen=True, slots=True)
class _OnnxBundle:
    session: Any
    tokenizer: Any
    max_length: int
    id2label: dict[int, int]


def clear_onnx_cache() -> None:
    _load_bundle.cache_clear()


@lru_cache(maxsize=1)
def _load_bundle(onnx_str: str, meta_str: str, tok_str: str) -> _OnnxBundle | None:
    onnx_path = Path(onnx_str)
    meta_path = Path(meta_str)
    tok_dir = Path(tok_str)
    if not onnx_path.is_file() or not meta_path.is_file() or not tok_dir.is_dir():
        return None
    try:
        import onnxruntime as ort
        from transformers import AutoTokenizer
    except ImportError:
        return None

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        session = ort.InferenceSession(
            str(onnx_path),
            providers=["CPUExecutionProvider"],
        )
        tokenizer = AutoTokenizer.from_pretrained(tok_dir)
    except Exception:
        return None

    id2label_raw = meta.get("id2label") or {"0": 1, "1": 2, "2": 3}
    id2label = {int(k): int(v) for k, v in id2label_raw.items()}
    return _OnnxBundle(
        session=session,
        tokenizer=tokenizer,
        max_length=int(meta.get("max_length", 128)),
        id2label=id2label,
    )


def predict_importance_onnx(
    text: str,
    *,
    onnx_path: Path | None = None,
    meta_path: Path | None = None,
    tokenizer_dir: Path | None = None,
    min_confidence: float = 0.45,
) -> ModelPrediction | None:
    """Pred через ONNX. None = нет артефакта / deps / низкая уверенность."""
    onnx = onnx_path or DEFAULT_ONNX_PATH
    meta = meta_path or onnx.with_suffix(".meta.json")
    tok = tokenizer_dir or DEFAULT_TOKENIZER_DIR
    bundle = _load_bundle(str(onnx), str(meta), str(tok))
    if bundle is None:
        return None

    encoded = bundle.tokenizer(
        text,
        return_tensors="np",
        truncation=True,
        padding="max_length",
        max_length=bundle.max_length,
    )
    outputs = bundle.session.run(
        None,
        {
            "input_ids": encoded["input_ids"],
            "attention_mask": encoded["attention_mask"],
        },
    )
    logits = outputs[0][0].tolist()
    probs = softmax(logits)
    # выравниваем probs под importance 1/2/3
    p_by_imp = {1: 0.0, 2: 0.0, 3: 0.0}
    for idx, p in enumerate(probs):
        imp = int(bundle.id2label.get(idx, idx + 1))
        p_by_imp[imp] = float(p)
    ordered = (p_by_imp[1], p_by_imp[2], p_by_imp[3])

    best_i = max(range(len(probs)), key=lambda i: probs[i])
    confidence = float(probs[best_i])
    if confidence < min_confidence:
        return None

    importance = int(bundle.id2label.get(best_i, best_i + 1))
    return ModelPrediction(
        importance=importance,
        disaster_flag=False,
        confidence=confidence,
        method="onnx",
        probs=ordered,
    )
