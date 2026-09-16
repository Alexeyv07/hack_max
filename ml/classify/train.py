"""Обучение importance-классификатора — sklearn baseline (НЕ runtime).

Основной путь (PyTorch): ml/classify/train_torch.py + DATA.md

Зависимости: pip install -e ".[ml]"

Запуск:
  # нужен data/train.jsonl (ручная разметка). Синтетика отдельно:
  python ml/classify/bootstrap_data.py          # → data/bootstrap.jsonl
  python ml/classify/train.py --data ml/classify/data/train.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "src"
DATA_DEFAULT = HERE / "data" / "train.jsonl"
CHECKPOINTS = HERE / "checkpoints"
ARTIFACTS = HERE / "artifacts"
JOBLIB_PATH = CHECKPOINTS / "pipeline.joblib"
JSON_PATH = ARTIFACTS / "importance_model.json"

# Runtime-токенizer из src (одинаковый с инференсом).
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parser_common.model_infer import FORMAT_V1  # noqa: E402
from parser_common.text_features import normalize_text  # noqa: E402


def _require_sklearn() -> None:
    try:
        import sklearn  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            f'Нужен optional extra: pip install -e ".[ml]"\nImportError: {exc}'
        ) from exc


def load_jsonl(path: Path) -> tuple[list[str], list[int]]:
    texts: list[str] = []
    labels: list[int] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            text = str(row.get("text") or "").strip()
            importance = int(row["importance"])
            if not text:
                raise ValueError(f"{path}:{line_no}: пустой text")
            if importance not in (1, 2, 3):
                raise ValueError(f"{path}:{line_no}: importance должен быть 1|2|3")
            texts.append(normalize_text(text))
            labels.append(importance)
    if len(texts) < 6:
        raise ValueError(f"Слишком мало примеров в {path}: {len(texts)}")
    return texts, labels


def export_json(vectorizer, clf, path: Path) -> None:
    """Сериализация TF-IDF + LogReg в JSON без sklearn на инференсе."""
    vocab = {str(k): int(v) for k, v in vectorizer.vocabulary_.items()}
    # idf_ выровнен по индексу фичи
    idf = [float(x) for x in vectorizer.idf_]
    classes = [int(c) for c in clf.classes_]
    coef = [[float(x) for x in row] for row in clf.coef_]
    intercept = [float(x) for x in clf.intercept_]
    payload = {
        "format": FORMAT_V1,
        "ngram_range": list(vectorizer.ngram_range),
        "analyzer": "word",
        "vocabulary": vocab,
        "idf": idf,
        "classes": classes,
        "coef": coef,
        "intercept": intercept,
        "disaster_is_importance_1": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def train(
    data_path: Path,
    *,
    joblib_out: Path = JOBLIB_PATH,
    json_out: Path = JSON_PATH,
    max_features: int = 4000,
    seed: int = 13,
) -> dict:
    _require_sklearn()
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline

    try:
        import joblib
    except ImportError as exc:
        raise SystemExit('Нужен joblib: pip install -e ".[ml]"') from exc

    texts, labels = load_jsonl(data_path)
    x_train, x_test, y_train, y_test = train_test_split(
        texts,
        labels,
        test_size=0.2,
        random_state=seed,
        stratify=labels,
    )

    pipe = Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    min_df=1,
                    max_features=max_features,
                    lowercase=True,
                    token_pattern=r"(?u)\b\w{2,}\b",
                ),
            ),
            (
                "clf",
                LogisticRegression(
                    max_iter=2000,
                    class_weight="balanced",
                    random_state=seed,
                ),
            ),
        ]
    )
    pipe.fit(x_train, y_train)
    y_pred = pipe.predict(x_test)
    report = classification_report(y_test, y_pred, digits=3)
    print(report)

    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, joblib_out)
    export_json(pipe.named_steps["tfidf"], pipe.named_steps["clf"], json_out)

    # Быстрая сверка JSON-инференса с sklearn на holdout
    from parser_common.model_infer import clear_model_cache, predict_importance

    clear_model_cache()
    mismatch = 0
    checked = 0
    for text, _gold in zip(x_test, y_test, strict=True):
        pred = predict_importance(text, path=json_out, min_confidence=0.0)
        sk = int(pipe.predict([text])[0])
        jp = None if pred is None else pred.importance
        checked += 1
        if jp != sk:
            mismatch += 1
    print(f"JSON vs sklearn mismatches on holdout: {mismatch}/{checked}")
    print(f"Saved joblib -> {joblib_out}")
    print(f"Saved runtime JSON -> {json_out}")
    return {"report": report, "mismatch": mismatch, "checked": checked}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train importance classifier (KAN-13)")
    parser.add_argument("--data", type=Path, default=DATA_DEFAULT)
    parser.add_argument("--max-features", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args()

    if not args.data.is_file():
        print(f"Нет датасета {args.data}. См. ml/classify/DATA.md")
        raise SystemExit(1)

    train(args.data, max_features=args.max_features, seed=args.seed)


if __name__ == "__main__":
    main()
