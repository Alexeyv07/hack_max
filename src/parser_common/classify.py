"""
Классификация важности события (ml_classify).

importance и disaster_flag — разные поля:
  importance 1|2|3 — вес/ранг для ленты
  disaster_flag — отдельный признак ЧС (карта, city-feed policy)

Каскад (первый успешный по confidence)::

    текст → ONNX rubert-tiny2 → keyword rules

ML предсказывает только importance.
disaster_flag всегда считается keyword-rules (не выводится из importance==1).

Обучение: ml/classify/train_torch.py (GPU). В src нет датасетов и train-кода.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from parser_common.model_onnx import clear_onnx_cache, predict_importance_onnx
from parser_common.text_features import normalize_text
from project.config import PROJECT_ROOT

_DEFAULT_DISASTER = (
    "катастроф",
    "цунами",
    "землетрясен",
    "взрыв",
    "теракт",
    "ядерн",
    "чрезвычайн",
    "эвакуац",
    "обрушен",
)
_DEFAULT_IMPORTANT = (
    "отключили воду",
    "отключение воды",
    "отключили свет",
    "отключение электричеств",
    "отключили газ",
    "авария",
    "прорыв",
    "пожар",
    "затоп",
    "ремонт теплосети",
    "без отопления",
    "канализац",
)

_RULES_PATH = PROJECT_ROOT / "ml" / "classify" / "rules.yaml"


@dataclass(frozen=True, slots=True)
class ClassifyResult:
    importance: int
    disaster_flag: bool
    method: str  # "onnx" | "rules"


@lru_cache(maxsize=1)
def _load_extra_keywords() -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not _RULES_PATH.is_file():
        return (), ()
    try:
        raw = yaml.safe_load(_RULES_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return (), ()
    disaster = tuple(str(x).lower() for x in (raw.get("disaster") or []) if x)
    important = tuple(str(x).lower() for x in (raw.get("important") or []) if x)
    return disaster, important


def clear_rules_cache() -> None:
    """Сброс кэшей rules + ONNX (тесты / hot-reload артефактов)."""
    _load_extra_keywords.cache_clear()
    clear_onnx_cache()


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _keyword_sets(text: str) -> tuple[bool, bool]:
    normalized = normalize_text(text)
    extra_disaster, extra_important = _load_extra_keywords()
    is_disaster = _contains_any(normalized, _DEFAULT_DISASTER + extra_disaster)
    is_important = _contains_any(normalized, _DEFAULT_IMPORTANT + extra_important)
    return is_disaster, is_important


def disaster_flag_by_rules(text: str) -> bool:
    """ЧС-маркер по keywords. Не зависит от predicted importance."""
    is_disaster, _ = _keyword_sets(text)
    return is_disaster


def classify_by_rules(text: str) -> ClassifyResult:
    """
    Rules без ML.
    При совпадении disaster-keywords: importance=1 и disaster_flag=True
    (эвристика fallback; в датасете/ML связка не обязательна).
    """
    is_disaster, is_important = _keyword_sets(text)
    if is_disaster:
        return ClassifyResult(importance=1, disaster_flag=True, method="rules")
    if is_important:
        return ClassifyResult(importance=2, disaster_flag=False, method="rules")
    return ClassifyResult(importance=3, disaster_flag=False, method="rules")


def classify_importance(
    text: str,
    *,
    use_model: bool = True,
    min_confidence: float = 0.45,
) -> ClassifyResult:
    """
    Каскад: ONNX → rules.

    ``use_model=False`` — только rules.
    При ML: importance из модели, disaster_flag из keyword-rules.
    """
    disaster = disaster_flag_by_rules(text)

    if use_model:
        onnx = predict_importance_onnx(text, min_confidence=min_confidence)
        if onnx is not None:
            return ClassifyResult(
                importance=onnx.importance,
                disaster_flag=disaster,
                method=onnx.method,
            )

    return classify_by_rules(text)


def rules_path() -> Path:
    return _RULES_PATH
