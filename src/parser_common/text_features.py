"""
Общая текстовая предобработка и мелкие мат. утилиты для classify.

Используется и keyword-rules, и TF-IDF JSON-инференсом
(должен совпадать с обучением sklearn в ml/classify/train.py).
"""

from __future__ import annotations

import math
import re

_WS = re.compile(r"\s+")
# Как у sklearn TfidfVectorizer(?u)\b\w\w+\b — слова ≥2 символов.
_TOKEN = re.compile(r"(?u)\b\w{2,}\b")


def collapse_ws(text: str) -> str:
    """Схлопнуть пробелы, без смены регистра (для title/body в ленте)."""
    return _WS.sub(" ", text).strip()


def normalize_text(text: str) -> str:
    """Нижний регистр, ё→е, схлопнуть пробелы (для classify / TF-IDF)."""
    return collapse_ws(text.lower().replace("ё", "е"))


def tokenize(text: str) -> list[str]:
    """Токены после normalize_text."""
    return _TOKEN.findall(normalize_text(text))


def iter_ngrams(tokens: list[str], ngram_range: tuple[int, int]) -> list[str]:
    """Word n-grams как в TfidfVectorizer(analyzer='word')."""
    lo, hi = ngram_range
    out: list[str] = []
    n = len(tokens)
    for size in range(lo, hi + 1):
        if size <= 0 or size > n:
            continue
        if size == 1:
            out.extend(tokens)
        else:
            out.extend(" ".join(tokens[i : i + size]) for i in range(n - size + 1))
    return out


def softmax(logits: list[float]) -> list[float]:
    """Численно устойчивый softmax."""
    peak = max(logits)
    exps = [math.exp(x - peak) for x in logits]
    total = sum(exps) or 1.0
    return [e / total for e in exps]
