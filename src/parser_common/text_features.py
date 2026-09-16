"""
Общая текстовая предобработка для classify (rules + softmax для ONNX).
"""

from __future__ import annotations

import math
import re

_WS = re.compile(r"\s+")


def collapse_ws(text: str) -> str:
    """Схлопнуть пробелы, без смены регистра (для title/body в ленте)."""
    return _WS.sub(" ", text).strip()


def normalize_text(text: str) -> str:
    """Нижний регистр, ё→е, схлопнуть пробелы (для keyword-rules)."""
    return collapse_ws(text.lower().replace("ё", "е"))


def softmax(logits: list[float]) -> list[float]:
    """Численно устойчивый softmax."""
    if not logits:
        return []
    m = max(logits)
    exps = [math.exp(x - m) for x in logits]
    s = sum(exps) or 1.0
    return [e / s for e in exps]
