"""Инференс importance-модели из JSON-артефакта (без sklearn/torch в runtime)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from parser_common.text_features import iter_ngrams, softmax, tokenize
from project.config import PROJECT_ROOT

FORMAT_V1 = "tfidf_logreg_v1"
DEFAULT_MODEL_PATH = PROJECT_ROOT / "ml" / "classify" / "artifacts" / "importance_model.json"


@dataclass(frozen=True, slots=True)
class ModelPrediction:
    """Единый ответ любого ML-бэкенда classify (ONNX / TF-IDF)."""

    importance: int
    disaster_flag: bool
    confidence: float
    method: str  # "onnx" | "tfidf"


def clear_model_cache() -> None:
    _load_model.cache_clear()


@lru_cache(maxsize=1)
def _load_model(path_str: str) -> dict[str, Any] | None:
    path = Path(path_str)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if raw.get("format") != FORMAT_V1:
        return None
    return raw


def _tfidf_vector(text: str, artifact: dict[str, Any]) -> dict[int, float]:
    ngram_range = (int(artifact["ngram_range"][0]), int(artifact["ngram_range"][1]))
    vocab: dict[str, int] = artifact["vocabulary"]
    idf: list[float] = artifact["idf"]
    tokens = tokenize(text)
    ngrams = iter_ngrams(tokens, ngram_range)
    if not ngrams:
        return {}

    counts: dict[int, float] = {}
    for gram in ngrams:
        idx = vocab.get(gram)
        if idx is None:
            continue
        counts[idx] = counts.get(idx, 0.0) + 1.0
    if not counts:
        return {}

    # raw tf * idf, затем L2 (как sklearn TfidfVectorizer default)
    weighted = {i: tf * idf[i] for i, tf in counts.items()}
    norm = math.sqrt(sum(v * v for v in weighted.values())) or 1.0
    return {i: v / norm for i, v in weighted.items()}


def _decision(vec: dict[int, float], artifact: dict[str, Any]) -> list[float]:
    coef: list[list[float]] = artifact["coef"]
    intercept: list[float] = artifact["intercept"]
    logits: list[float] = []
    for class_i, bias in enumerate(intercept):
        score = bias
        row = coef[class_i]
        for feat_i, value in vec.items():
            score += row[feat_i] * value
        logits.append(score)
    return logits


def predict_importance(
    text: str,
    *,
    path: Path | None = None,
    min_confidence: float = 0.45,
) -> ModelPrediction | None:
    """
    Pred importance 1–3. None = нет файла / битый формат / низкая уверенность.

    disaster_flag в ModelPrediction всегда False: флаг ЧС ставит classify
    через keyword-rules, не через importance==1.
    """
    artifact = _load_model(str(path or DEFAULT_MODEL_PATH))
    if artifact is None:
        return None

    vec = _tfidf_vector(text, artifact)
    if not vec:
        return None

    logits = _decision(vec, artifact)
    probs = softmax(logits)
    best_i = max(range(len(probs)), key=lambda i: probs[i])
    confidence = probs[best_i]
    if confidence < min_confidence:
        return None

    classes: list[int] = [int(c) for c in artifact["classes"]]
    importance = classes[best_i]
    return ModelPrediction(
        importance=importance,
        disaster_flag=False,
        confidence=confidence,
        method="tfidf",
    )
