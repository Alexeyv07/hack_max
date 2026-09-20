"""Эмбеддинги текста для cosine-дедупа.

Приоритет:
  1) ONNX mean-pool (ml/dedup/artifacts/), если есть
  2) transformers AutoModel mean-pool (pretrained rubert-tiny2)
  3) hash n-gram fallback (тесты / без ML deps)
"""

from __future__ import annotations

import hashlib
import math
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from project.config import PROJECT_ROOT

DEFAULT_MODEL = "cointegrated/rubert-tiny2"
DEFAULT_ONNX = PROJECT_ROOT / "ml" / "dedup" / "artifacts" / "embed_model.onnx"
DEFAULT_META = DEFAULT_ONNX.with_suffix(".meta.json")
DEFAULT_TOKENIZER = PROJECT_ROOT / "ml" / "dedup" / "artifacts" / "tokenizer"


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm < 1e-12:
        return vec
    return vec / norm


def clear_embed_cache() -> None:
    _load_transformers.cache_clear()
    _load_onnx.cache_clear()


@lru_cache(maxsize=1)
def _load_onnx(onnx_str: str, meta_str: str, tok_str: str) -> tuple[Any, Any, int] | None:
    onnx_path = Path(onnx_str)
    meta_path = Path(meta_str)
    tok_dir = Path(tok_str)
    if not onnx_path.is_file() or not tok_dir.is_dir():
        return None
    try:
        import json

        import onnxruntime as ort
        from transformers import AutoTokenizer
    except ImportError:
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        session = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        tokenizer = AutoTokenizer.from_pretrained(tok_dir)
        max_length = int(meta.get("max_length", 128))
        return session, tokenizer, max_length
    except Exception:
        return None


@lru_cache(maxsize=1)
def _load_transformers(model_name: str) -> tuple[Any, Any] | None:
    try:
        from transformers import AutoModel, AutoTokenizer
    except ImportError:
        return None
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModel.from_pretrained(model_name)
        model.eval()
        return tokenizer, model
    except Exception:
        return None


def _mean_pool(last_hidden: Any, attention_mask: Any) -> Any:
    mask = attention_mask.unsqueeze(-1).expand(last_hidden.size()).float()
    summed = (last_hidden * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts


def _embed_onnx(text: str) -> np.ndarray | None:
    bundle = _load_onnx(str(DEFAULT_ONNX), str(DEFAULT_META), str(DEFAULT_TOKENIZER))
    if bundle is None:
        return None
    session, tokenizer, max_length = bundle
    encoded = tokenizer(
        text,
        return_tensors="np",
        truncation=True,
        padding="max_length",
        max_length=max_length,
    )
    outputs = session.run(
        None,
        {
            "input_ids": encoded["input_ids"],
            "attention_mask": encoded["attention_mask"],
        },
    )
    vec = np.asarray(outputs[0][0], dtype=np.float32)
    return _l2_normalize(vec)


def _embed_transformers(text: str, *, model_name: str = DEFAULT_MODEL) -> np.ndarray | None:
    import torch

    loaded = _load_transformers(model_name)
    if loaded is None:
        return None
    tokenizer, model = loaded
    encoded = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=128,
    )
    with torch.no_grad():
        out = model(**encoded)
        pooled = _mean_pool(out.last_hidden_state, encoded["attention_mask"])
    vec = pooled[0].cpu().numpy().astype(np.float32)
    return _l2_normalize(vec)


def _embed_hash(text: str, *, dim: int = 256) -> np.ndarray:
    """Характерные n-gram хеши — только fallback для тестов без ML."""
    vec = np.zeros(dim, dtype=np.float32)
    norm = text.lower().replace("ё", "е")
    tokens = norm.split()
    grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
    for gram in grams:
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        idx = struct.unpack("<Q", digest)[0] % dim
        sign = 1.0 if digest[0] % 2 == 0 else -1.0
        vec[idx] += sign
    return _l2_normalize(vec)


def embed_text(text: str, *, allow_hash_fallback: bool = True) -> np.ndarray:
    cleaned = " ".join(text.split())
    if not cleaned:
        return _embed_hash("", dim=256)

    for fn in (_embed_onnx, _embed_transformers):
        try:
            vec = fn(cleaned)
        except Exception:
            vec = None
        if vec is not None:
            return vec

    if not allow_hash_fallback:
        raise RuntimeError("Нет embed-модели и hash fallback запрещён")
    return _embed_hash(cleaned)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(
        np.dot(a, b) / (max(float(np.linalg.norm(a)), 1e-12) * max(float(np.linalg.norm(b)), 1e-12))
    )


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))
