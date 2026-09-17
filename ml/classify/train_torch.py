"""Fine-tune rubert-tiny2 для importance 1–3 (PyTorch / HuggingFace).

Зависимости:
  pip install torch --index-url https://download.pytorch.org/whl/cu124
  pip install -e ".[ml]"

Данные — см. ml/classify/DATA.md

Запуск:
  # data/train.jsonl обязателен. Синтетика: bootstrap_data.py → bootstrap.jsonl
  python ml/classify/train_torch.py --config ml/classify/config_torch.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from dataset_io import (  # noqa: E402
    ClassifyExample,
    class_counts,
    id_to_label,
    label_to_id,
    load_jsonl,
)


def _require_torch_stack() -> None:
    missing: list[str] = []
    for name in ("torch", "transformers", "datasets", "sklearn", "accelerate"):
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if missing:
        raise SystemExit(
            "Не хватает пакетов: "
            + ", ".join(missing)
            + "\nУстановите: pip install torch --index-url https://download.pytorch.org/whl/cu124"
            '\nЗатем: pip install -e ".[ml]"'
        )


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


def _split_train_val(
    rows: list[ClassifyExample],
    val_ratio: float,
    seed: int,
) -> tuple[list[ClassifyExample], list[ClassifyExample]]:
    from sklearn.model_selection import train_test_split

    labels = [r.importance for r in rows]
    train_rows, val_rows = train_test_split(
        rows,
        test_size=val_ratio,
        random_state=seed,
        stratify=labels,
    )
    return list(train_rows), list(val_rows)


def _class_weights(rows: list[ClassifyExample], device: Any) -> Any:
    import torch

    counts = Counter(label_to_id(r.importance) for r in rows)
    n_classes = 3
    total = sum(counts.values())
    weights = []
    for i in range(n_classes):
        c = counts.get(i, 1)
        weights.append(total / (n_classes * c))
    return torch.tensor(weights, dtype=torch.float32, device=device)


def _build_hf_dataset(rows: list[ClassifyExample], tokenizer, max_length: int):
    from datasets import Dataset

    def tokenize_batch(batch: dict[str, list]) -> dict[str, list]:
        enc = tokenizer(
            batch["text"],
            truncation=True,
            padding=False,
            max_length=max_length,
        )
        enc["labels"] = batch["labels"]
        return enc

    raw = Dataset.from_dict(
        {
            "text": [r.text for r in rows],
            "labels": [label_to_id(r.importance) for r in rows],
        }
    )
    return raw.map(tokenize_batch, batched=True, remove_columns=["text"])


def train(config_path: Path) -> dict[str, Any]:
    _require_torch_stack()

    import numpy as np
    import torch
    from export_onnx import export_onnx
    from sklearn.metrics import classification_report, f1_score
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        EarlyStoppingCallback,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    cfg = _load_config(config_path)
    set_seed(int(cfg.get("seed", 13)))

    train_path = _resolve(cfg["train_path"], base=ROOT)
    assert train_path is not None
    if not train_path.is_file():
        raise SystemExit(f"Нет датасета {train_path}\nНет train.jsonl — см. ml/classify/DATA.md")

    train_rows = load_jsonl(train_path)
    val_path = _resolve(cfg.get("val_path"), base=ROOT)
    if val_path and val_path.is_file():
        val_rows = load_jsonl(val_path)
    else:
        train_rows, val_rows = _split_train_val(
            train_rows,
            float(cfg.get("val_ratio", 0.15)),
            int(cfg.get("seed", 13)),
        )

    test_path = _resolve(cfg.get("test_path"), base=ROOT)
    test_rows = load_jsonl(test_path) if test_path and test_path.is_file() else []

    print("train counts:", class_counts(train_rows))
    print("val counts:", class_counts(val_rows))
    if test_rows:
        print("test counts:", class_counts(test_rows))

    model_name = cfg.get("model_name", "cointegrated/rubert-tiny2")
    max_length = int(cfg.get("max_length", 128))
    tokenizer = AutoTokenizer.from_pretrained(model_name)

    id2label = {0: "1", 1: "2", 2: "3"}
    label2id = {"1": 0, "2": 1, "3": 2}
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=3,
        id2label=id2label,
        label2id=label2id,
    )

    train_ds = _build_hf_dataset(train_rows, tokenizer, max_length)
    val_ds = _build_hf_dataset(val_rows, tokenizer, max_length)
    test_ds = _build_hf_dataset(test_rows, tokenizer, max_length) if test_rows else None

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_fp16 = bool(cfg.get("fp16", True)) and device.type == "cuda"
    print(f"device={device} fp16={use_fp16}")

    output_dir = _resolve(
        cfg.get("output_dir", "ml/classify/checkpoints/rubert_importance"),
        base=ROOT,
    )
    assert output_dir is not None
    best_dir = output_dir / "best"
    output_dir.mkdir(parents=True, exist_ok=True)

    def compute_metrics(eval_pred: Any) -> dict[str, float]:
        logits, labels = eval_pred
        preds = np.argmax(logits, axis=-1)
        return {
            "macro_f1": float(f1_score(labels, preds, average="macro")),
            "accuracy": float((preds == labels).mean()),
        }

    class_weight = cfg.get("class_weight")
    weights = _class_weights(train_rows, device) if class_weight == "balanced" else None

    class WeightedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            labels = inputs.pop("labels")
            outputs = model(**inputs)
            logits = outputs.logits
            if weights is not None:
                loss_f = torch.nn.CrossEntropyLoss(weight=weights)
            else:
                loss_f = torch.nn.CrossEntropyLoss()
            loss = loss_f(logits, labels)
            return (loss, outputs) if return_outputs else loss

    args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=float(cfg.get("epochs", 4)),
        per_device_train_batch_size=int(cfg.get("train_batch_size", 16)),
        per_device_eval_batch_size=int(cfg.get("eval_batch_size", 32)),
        learning_rate=float(cfg.get("learning_rate", 2e-5)),
        weight_decay=float(cfg.get("weight_decay", 0.01)),
        warmup_ratio=float(cfg.get("warmup_ratio", 0.06)),
        max_grad_norm=float(cfg.get("max_grad_norm", 1.0)),
        gradient_accumulation_steps=int(cfg.get("gradient_accumulation_steps", 1)),
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
        fp16=use_fp16,
        logging_steps=int(cfg.get("logging_steps", 20)),
        save_total_limit=int(cfg.get("save_total_limit", 2)),
        report_to=[],
        seed=int(cfg.get("seed", 13)),
        dataloader_num_workers=int(cfg.get("dataloader_num_workers", 0)),
    )

    callbacks = []
    patience = cfg.get("early_stopping_patience")
    if patience:
        callbacks.append(EarlyStoppingCallback(early_stopping_patience=int(patience)))

    trainer = WeightedTrainer(
        model=model,
        args=args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        processing_class=tokenizer,
        data_collator=DataCollatorWithPadding(tokenizer=tokenizer),
        compute_metrics=compute_metrics,
        callbacks=callbacks,
    )

    trainer.train()
    metrics = trainer.evaluate()
    print("val metrics:", metrics)

    best_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(best_dir))
    tokenizer.save_pretrained(str(best_dir))

    val_pred = trainer.predict(val_ds)
    y_true = val_pred.label_ids
    y_hat = np.argmax(val_pred.predictions, axis=-1)
    print(
        classification_report(
            y_true,
            y_hat,
            target_names=["imp1", "imp2", "imp3"],
            digits=3,
        )
    )

    report: dict[str, Any] = {"val": metrics, "train_counts": class_counts(train_rows)}
    if test_ds is not None:
        test_metrics = trainer.predict(test_ds)
        report["test_macro_f1"] = float(
            f1_score(
                test_metrics.label_ids,
                np.argmax(test_metrics.predictions, axis=-1),
                average="macro",
            )
        )
        print("test macro_f1:", report["test_macro_f1"])

    (output_dir / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if cfg.get("export_onnx", True):
        onnx_path = _resolve(
            cfg.get("onnx_path", "ml/classify/artifacts/importance_model.onnx"),
            base=ROOT,
        )
        tok_dir = _resolve(
            cfg.get("tokenizer_dir", "ml/classify/artifacts/tokenizer"),
            base=ROOT,
        )
        assert onnx_path is not None and tok_dir is not None
        export_onnx(best_dir, onnx_path, tok_dir, max_length=max_length)

    _ = id_to_label(0)
    print(f"Best checkpoint -> {best_dir}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train rubert importance classifier")
    parser.add_argument(
        "--config",
        type=Path,
        default=HERE / "config_torch.yaml",
    )
    args = parser.parse_args()
    if not args.config.is_file():
        raise SystemExit(f"Нет конфига: {args.config}")
    train(args.config.resolve())


if __name__ == "__main__":
    main()
