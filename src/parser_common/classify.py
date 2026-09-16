"""Эвристический classify importance (ml_classify MVP без GPU/LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from project.config import PROJECT_ROOT

# Компактные дефолты в коде. Расширения/датасеты — только в ml/ (вне src).
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


@lru_cache(maxsize=1)
def _load_extra_keywords() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Опционально подтянуть keywords из ml/classify/rules.yaml (не из src)."""
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
    """Сброс кэша правил (тесты)."""
    _load_extra_keywords.cache_clear()


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def classify_importance(text: str) -> ClassifyResult:
    """
    Rules + keywords:
      - катастрофы → importance=1 + disaster_flag
      - важное ЖКХ → importance=2
      - иначе бытовуха → importance=3
    """
    normalized = re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip()
    extra_disaster, extra_important = _load_extra_keywords()
    disaster_kw = _DEFAULT_DISASTER + extra_disaster
    important_kw = _DEFAULT_IMPORTANT + extra_important

    if _contains_any(normalized, disaster_kw):
        return ClassifyResult(importance=1, disaster_flag=True)
    if _contains_any(normalized, important_kw):
        return ClassifyResult(importance=2, disaster_flag=False)
    return ClassifyResult(importance=3, disaster_flag=False)


def rules_path() -> Path:
    """Путь к внешнему yaml (для тестов/доков)."""
    return _RULES_PATH
