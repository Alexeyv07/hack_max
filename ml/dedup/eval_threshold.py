"""Подбор cosine-порогов duplicate / update по размеченным парам.

Запуск из корня репо:
  python ml/dedup/bootstrap_pairs.py
  python ml/dedup/eval_threshold.py --pairs ml/dedup/data/bootstrap_pairs.jsonl

Embeddings: rubert-tiny2 mean-pool (transformers). Если недоступны —
hash n-gram fallback (только smoke).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

LABELS = ("duplicate", "update", "unrelated")


@dataclass(frozen=True, slots=True)
class PairExample:
    text_a: str
    text_b: str
    label: str
    source: str | None = None


def _load_config(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise SystemExit(f"Конфиг должен быть mapping: {path}")
    return raw


def _resolve(path_like: str | None, *, base: Path) -> Path | None:
    if path_like is None:
        return None
    path = Path(path_like)
    if not path.is_absolute():
        path = (base / path).resolve()
    return path


def load_pairs(path: Path) -> list[PairExample]:
    rows: list[PairExample] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            loc = f"{path}:{line_no}"
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{loc}: битый JSON") from exc
            a = str(raw.get("text_a") or "").strip()
            b = str(raw.get("text_b") or "").strip()
            label = str(raw.get("label") or "").strip()
            if not a or not b:
                raise ValueError(f"{loc}: пустой text_a/text_b")
            if label not in LABELS:
                raise ValueError(f"{loc}: label должен быть {'|'.join(LABELS)}")
            source = raw.get("source")
            rows.append(
                PairExample(
                    text_a=a,
                    text_b=b,
                    label=label,
                    source=str(source) if source is not None else None,
                )
            )
    if not rows:
        raise ValueError(f"Пустой датасет: {path}")
    return rows


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=True)))


def _hash_embed(text: str, dim: int = 256) -> list[float]:
    """Простой bag символьных 3-gram → фиксированный вектор (smoke fallback)."""
    text = text.lower()
    grams = [text[i : i + 3] for i in range(max(len(text) - 2, 1))]
    counts: Counter[int] = Counter()
    for g in grams:
        h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
        counts[h % dim] += 1
    vec = [float(counts.get(i, 0)) for i in range(dim)]
    return _l2_normalize(vec)


def _try_transformer_embedder(model_name: str, max_length: int, batch_size: int):
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError:
        return None

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    model.eval()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    @torch.no_grad()
    def embed_texts(texts: Sequence[str]) -> list[list[float]]:
        out_vecs: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start : start + batch_size])
            enc = tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            enc = {k: v.to(device) for k, v in enc.items()}
            hidden = model(**enc).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            summed = (hidden * mask).sum(dim=1)
            counts = mask.sum(dim=1).clamp_min(1.0)
            mean = summed / counts
            mean = torch.nn.functional.normalize(mean, p=2, dim=1)
            out_vecs.extend(mean.cpu().tolist())
        return out_vecs

    return embed_texts


def embed_corpus(
    texts: Sequence[str],
    *,
    model_name: str,
    max_length: int,
    batch_size: int,
    allow_hash_fallback: bool,
) -> tuple[list[list[float]], str]:
    embed_fn = _try_transformer_embedder(model_name, max_length, batch_size)
    if embed_fn is not None:
        return embed_fn(texts), "rubert_mean_pool"
    if not allow_hash_fallback:
        raise SystemExit(
            'transformers/torch недоступны; поставьте pip install -e ".[ml]" '
            "или включите allow_hash_fallback"
        )
    print("WARN: transformers недоступны — hash n-gram fallback")
    return [_hash_embed(t) for t in texts], "hash_ngram"


def predict_label(sim: float, dup_thr: float, upd_thr: float) -> str:
    if sim >= dup_thr:
        return "duplicate"
    if sim >= upd_thr:
        return "update"
    return "unrelated"


def _f1_for_class(y_true: Sequence[str], y_pred: Sequence[str], target: str) -> float:
    tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == target and p == target)
    fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t != target and p == target)
    fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == target and p != target)
    if tp == 0:
        return 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec)


def macro_f1(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    scores = [_f1_for_class(y_true, y_pred, lab) for lab in LABELS]
    return float(sum(scores) / len(scores))


def confusion(y_true: Sequence[str], y_pred: Sequence[str]) -> dict[str, dict[str, int]]:
    matrix = {a: {b: 0 for b in LABELS} for a in LABELS}
    for t, p in zip(y_true, y_pred, strict=True):
        matrix[t][p] += 1
    return matrix


def _frange(start: float, stop: float, step: float) -> Iterable[float]:
    n = int(round((stop - start) / step))
    for i in range(n + 1):
        yield round(start + i * step, 4)


def grid_search(
    sims: Sequence[float],
    labels: Sequence[str],
    grid: dict[str, Any],
) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    for dup in _frange(
        float(grid.get("duplicate_min", 0.75)),
        float(grid.get("duplicate_max", 0.95)),
        float(grid.get("duplicate_step", 0.01)),
    ):
        for upd in _frange(
            float(grid.get("update_min", 0.50)),
            float(grid.get("update_max", 0.90)),
            float(grid.get("update_step", 0.01)),
        ):
            if dup < upd:
                continue
            preds = [predict_label(s, dup, upd) for s in sims]
            score = macro_f1(labels, preds)
            cand = {
                "duplicate_threshold": dup,
                "update_threshold": upd,
                "macro_f1": score,
                "f1_duplicate": _f1_for_class(labels, preds, "duplicate"),
                "f1_update": _f1_for_class(labels, preds, "update"),
                "f1_unrelated": _f1_for_class(labels, preds, "unrelated"),
            }
            if best is None or cand["macro_f1"] > best["macro_f1"]:
                best = cand
                best["confusion"] = confusion(labels, preds)
    assert best is not None
    return best


def evaluate(
    pairs: list[PairExample],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    model_name = str(cfg.get("model_name", "cointegrated/rubert-tiny2"))
    max_length = int(cfg.get("max_length", 128))
    batch_size = int(cfg.get("batch_size", 32))
    allow_hash = bool(cfg.get("allow_hash_fallback", True))

    # уникальные тексты → один encode
    uniq: list[str] = []
    index: dict[str, int] = {}
    for p in pairs:
        for t in (p.text_a, p.text_b):
            if t not in index:
                index[t] = len(uniq)
                uniq.append(t)

    vectors, backend = embed_corpus(
        uniq,
        model_name=model_name,
        max_length=max_length,
        batch_size=batch_size,
        allow_hash_fallback=allow_hash,
    )
    sims = [_cosine(vectors[index[p.text_a]], vectors[index[p.text_b]]) for p in pairs]
    labels = [p.label for p in pairs]

    grid = cfg.get("grid") or {}
    best = grid_search(sims, labels, grid)

    # метрики на дефолтных порогах из конфига
    dup_def = float(cfg.get("duplicate_threshold", 0.88))
    upd_def = float(cfg.get("update_threshold", 0.72))
    preds_def = [predict_label(s, dup_def, upd_def) for s in sims]
    defaults = {
        "duplicate_threshold": dup_def,
        "update_threshold": upd_def,
        "macro_f1": macro_f1(labels, preds_def),
        "f1_duplicate": _f1_for_class(labels, preds_def, "duplicate"),
        "f1_update": _f1_for_class(labels, preds_def, "update"),
        "f1_unrelated": _f1_for_class(labels, preds_def, "unrelated"),
        "confusion": confusion(labels, preds_def),
    }

    by_label = Counter(labels)
    return {
        "backend": backend,
        "n_pairs": len(pairs),
        "label_counts": dict(by_label),
        "sim_mean": float(sum(sims) / len(sims)),
        "defaults": defaults,
        "best_grid": best,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Grid-search dedup cosine thresholds")
    parser.add_argument(
        "--config",
        type=Path,
        default=HERE / "config.yaml",
    )
    parser.add_argument(
        "--pairs",
        type=Path,
        default=None,
        help="JSONL пар (default: config pairs_path или bootstrap)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="куда писать thresholds.json",
    )
    args = parser.parse_args()
    if not args.config.is_file():
        raise SystemExit(f"Нет конфига: {args.config}")

    cfg = _load_config(args.config.resolve())
    pairs_path = args.pairs
    if pairs_path is None:
        pairs_path = _resolve(cfg.get("pairs_path"), base=ROOT)
        if pairs_path is None or not pairs_path.is_file():
            pairs_path = _resolve(cfg.get("bootstrap_pairs_path"), base=ROOT)
    else:
        pairs_path = pairs_path.resolve()

    assert pairs_path is not None
    if not pairs_path.is_file():
        raise SystemExit(
            f"Нет файла пар: {pairs_path}\nСначала: python ml/dedup/bootstrap_pairs.py"
        )

    pairs = load_pairs(pairs_path)
    report = evaluate(pairs, cfg)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    out = args.out
    if out is None:
        art = _resolve(cfg.get("artifacts_dir", "ml/dedup/artifacts"), base=ROOT)
        assert art is not None
        out = art / "thresholds.json"
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "dedup_thresholds_v1",
        "source_pairs": str(pairs_path),
        "backend": report["backend"],
        "recommended": {
            "duplicate_threshold": report["best_grid"]["duplicate_threshold"],
            "update_threshold": report["best_grid"]["update_threshold"],
        },
        "metrics": report,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote -> {out}")


if __name__ == "__main__":
    main()
