"""
ONNX-инференс time-window (active_from / active_to) — multi-head rubert-tiny2.

Артефакты (ml/time/train_torch.py / export_onnx.py):
  - ml/time/artifacts/time_window_model.onnx
  - ml/time/artifacts/time_window_model.meta.json
  - ml/time/artifacts/tokenizer/

Нет deps / файлов → None (выше не подставляем rules — только ML).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from project.config import PROJECT_ROOT

DEFAULT_ONNX_PATH = PROJECT_ROOT / "ml" / "time" / "artifacts" / "time_window_model.onnx"
DEFAULT_META_PATH = DEFAULT_ONNX_PATH.with_suffix(".meta.json")
DEFAULT_TOKENIZER_DIR = PROJECT_ROOT / "ml" / "time" / "artifacts" / "tokenizer"


@dataclass(frozen=True, slots=True)
class TimeWindowPrediction:
    active_from: datetime | None
    active_to: datetime | None
    confidence: float
    method: str  # "onnx"


@dataclass(frozen=True, slots=True)
class _OnnxBundle:
    session: Any
    tokenizer: Any
    max_length: int
    has_threshold: float


def clear_time_onnx_cache() -> None:
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

    return _OnnxBundle(
        session=session,
        tokenizer=tokenizer,
        max_length=int(meta.get("max_length", 160)),
        has_threshold=float(meta.get("has_threshold", 0.5)),
    )


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = __import__("math").exp(-x)
        return 1.0 / (1.0 + z)
    z = __import__("math").exp(x)
    return z / (1.0 + z)


def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def predict_time_window_onnx(
    text: str,
    *,
    reference: datetime | None = None,
    onnx_path: Path | None = None,
    meta_path: Path | None = None,
    tokenizer_dir: Path | None = None,
    min_confidence: float = 0.45,
) -> TimeWindowPrediction | None:
    """Pred через ONNX. None = нет артефакта / deps / низкая уверенность."""
    onnx = onnx_path or DEFAULT_ONNX_PATH
    meta = meta_path or onnx.with_suffix(".meta.json")
    tok = tokenizer_dir or DEFAULT_TOKENIZER_DIR
    bundle = _load_bundle(str(onnx), str(meta), str(tok))
    if bundle is None:
        return None

    ref = _as_aware(reference or datetime.now(UTC))
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
    # ожидаемый порядок: has_from_logit, has_to_logit, from_offset, to_offset
    has_from_logit = float(outputs[0].reshape(-1)[0])
    has_to_logit = float(outputs[1].reshape(-1)[0])
    from_offset = float(outputs[2].reshape(-1)[0])
    to_offset = float(outputs[3].reshape(-1)[0])

    p_from = _sigmoid(has_from_logit)
    p_to = _sigmoid(has_to_logit)
    confidence = (
        max(p_from, p_to)
        if (p_from >= bundle.has_threshold or p_to >= bundle.has_threshold)
        else max(p_from, p_to)
    )
    if (
        confidence < min_confidence
        and p_from < bundle.has_threshold
        and p_to < bundle.has_threshold
    ):
        return None

    active_from = ref + timedelta(hours=from_offset) if p_from >= bundle.has_threshold else None
    active_to = ref + timedelta(hours=to_offset) if p_to >= bundle.has_threshold else None
    if active_from is None and active_to is None:
        return None

    return TimeWindowPrediction(
        active_from=active_from,
        active_to=active_to,
        confidence=float(confidence),
        method="onnx",
    )
