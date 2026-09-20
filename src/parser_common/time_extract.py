"""Извлечение active_from / active_to — только ML (ONNX), без keyword-rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from parser_common.time_onnx import TimeWindowPrediction, predict_time_window_onnx


@dataclass(frozen=True, slots=True)
class TimeExtractResult:
    active_from: datetime | None
    active_to: datetime | None
    method: str  # "onnx" | "none"


def extract_active_window(
    text: str,
    *,
    reference: datetime | None = None,
    use_model: bool = True,
    min_confidence: float = 0.45,
) -> TimeExtractResult:
    """
    Окно действия события.

    Rules намеренно не используем (продукт: rules не тянут).
    Без ONNX-артефакта → (None, None).
    """
    if use_model:
        try:
            from project.config import get_settings

            enrich = get_settings().ml_enrich
            if not enrich.time_enabled:
                return TimeExtractResult(None, None, "none")
            min_confidence = enrich.time_min_confidence
        except Exception:
            pass

    if not use_model or not text.strip():
        return TimeExtractResult(None, None, "none")

    pred: TimeWindowPrediction | None = predict_time_window_onnx(
        text,
        reference=reference,
        min_confidence=min_confidence,
    )
    if pred is None:
        return TimeExtractResult(None, None, "none")

    active_from = pred.active_from
    active_to = pred.active_to
    if active_from is not None and active_to is not None and active_to < active_from:
        active_from, active_to = active_to, active_from

    return TimeExtractResult(
        active_from=active_from,
        active_to=active_to,
        method=pred.method,
    )
