"""Fine-tune rubert-tiny2 для active_from / active_to (multi-head).

Зависимости:
  pip install torch --index-url https://download.pytorch.org/whl/cu124
  pip install -e ".[ml]"

Данные — см. ml/time/DATA.md

Запуск:
  python ml/time/bootstrap_data.py
  # затем положить/скопировать данные в data/train.jsonl
  python ml/time/train_torch.py --config ml/time/config_torch.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from dataset_io import TimeExample, bound_counts, load_jsonl  # noqa: E402


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
    rows: list[TimeExample],
    val_ratio: float,
    seed: int,
) -> tuple[list[TimeExample], list[TimeExample]]:
    from sklearn.model_selection import train_test_split

    strata = []
    for r in rows:
        if r.has_from and r.has_to:
            strata.append("both")
        elif r.has_from:
            strata.append("from")
        elif r.has_to:
            strata.append("to")
        else:
            strata.append("none")
    try:
        train_rows, val_rows = train_test_split(
            rows,
            test_size=val_ratio,
            random_state=seed,
            stratify=strata,
        )
    except ValueError:
        train_rows, val_rows = train_test_split(
            rows,
            test_size=val_ratio,
            random_state=seed,
        )
    return list(train_rows), list(val_rows)


def _build_hf_dataset(rows: list[TimeExample], tokenizer, max_length: int):
    from datasets import Dataset

    def tokenize_batch(batch: dict[str, list]) -> dict[str, list]:
        enc = tokenizer(
            batch["text"],
            truncation=True,
            padding=False,
            max_length=max_length,
        )
        enc["has_from"] = batch["has_from"]
        enc["has_to"] = batch["has_to"]
        enc["from_offset"] = batch["from_offset"]
        enc["to_offset"] = batch["to_offset"]
        return enc

    raw = Dataset.from_dict(
        {
            "text": [r.text for r in rows],
            "has_from": [1.0 if r.has_from else 0.0 for r in rows],
            "has_to": [1.0 if r.has_to else 0.0 for r in rows],
            "from_offset": [float(r.from_offset_hours or 0.0) for r in rows],
            "to_offset": [float(r.to_offset_hours or 0.0) for r in rows],
        }
    )
    return raw.map(tokenize_batch, batched=True, remove_columns=["text"])


def _make_model(model_name: str):
    import torch
    from torch import nn
    from transformers import AutoConfig, AutoModel

    class TimeWindowMultiHead(nn.Module):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.config = AutoConfig.from_pretrained(name)
            self.encoder = AutoModel.from_pretrained(name)
            hidden = int(self.config.hidden_size)
            self.has_from_head = nn.Linear(hidden, 1)
            self.has_to_head = nn.Linear(hidden, 1)
            self.from_offset_head = nn.Linear(hidden, 1)
            self.to_offset_head = nn.Linear(hidden, 1)

        def forward(
            self,
            input_ids: torch.Tensor,
            attention_mask: torch.Tensor,
            **_: Any,
        ) -> dict[str, torch.Tensor]:
            out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
            cls = out.last_hidden_state[:, 0]
            return {
                "has_from_logit": self.has_from_head(cls).squeeze(-1),
                "has_to_logit": self.has_to_head(cls).squeeze(-1),
                "from_offset": self.from_offset_head(cls).squeeze(-1),
                "to_offset": self.to_offset_head(cls).squeeze(-1),
            }

    return TimeWindowMultiHead(model_name)


def train(config_path: Path) -> dict[str, Any]:
    _require_torch_stack()

    import numpy as np
    import torch
    from export_onnx import export_onnx
    from sklearn.metrics import f1_score
    from torch import nn
    from torch.utils.data import DataLoader
    from transformers import AutoTokenizer, DataCollatorWithPadding, set_seed

    cfg = _load_config(config_path)
    set_seed(int(cfg.get("seed", 19)))

    train_path = _resolve(cfg["train_path"], base=ROOT)
    assert train_path is not None
    if not train_path.is_file():
        raise SystemExit(
            f"Нет датасета {train_path}\n"
            "Соберите данные: python ml/time/build_train_from_sources.py\n"
            "См. ml/time/DATA.md"
        )

    train_rows = load_jsonl(train_path)
    val_path = _resolve(cfg.get("val_path"), base=ROOT)
    if val_path and val_path.is_file():
        val_rows = load_jsonl(val_path)
    else:
        train_rows, val_rows = _split_train_val(
            train_rows,
            float(cfg.get("val_ratio", 0.15)),
            int(cfg.get("seed", 19)),
        )

    test_path = _resolve(cfg.get("test_path"), base=ROOT)
    test_rows = load_jsonl(test_path) if test_path and test_path.is_file() else []

    print("train bounds:", bound_counts(train_rows))
    print("val bounds:", bound_counts(val_rows))
    if test_rows:
        print("test bounds:", bound_counts(test_rows))

    model_name = cfg.get("model_name", "cointegrated/rubert-tiny2")
    max_length = int(cfg.get("max_length", 160))
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = _make_model(model_name)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_fp16 = bool(cfg.get("fp16", True)) and device.type == "cuda"
    print(f"device={device} fp16={use_fp16}")
    model.to(device)

    train_ds = _build_hf_dataset(train_rows, tokenizer, max_length)
    val_ds = _build_hf_dataset(val_rows, tokenizer, max_length)

    collator = DataCollatorWithPadding(tokenizer=tokenizer)
    label_keys = ("has_from", "has_to", "from_offset", "to_offset")

    def collate(features: list[dict[str, Any]]) -> dict[str, Any]:
        labels = {
            k: torch.tensor([f.pop(k) for f in features], dtype=torch.float32) for k in label_keys
        }
        batch = collator(features)
        batch.update(labels)
        return batch

    train_loader = DataLoader(
        train_ds,
        batch_size=int(cfg.get("train_batch_size", 12)),
        shuffle=True,
        collate_fn=collate,
        num_workers=int(cfg.get("dataloader_num_workers", 0)),
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=int(cfg.get("eval_batch_size", 24)),
        shuffle=False,
        collate_fn=collate,
        num_workers=int(cfg.get("dataloader_num_workers", 0)),
    )

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(cfg.get("learning_rate", 2e-5)),
        weight_decay=float(cfg.get("weight_decay", 0.01)),
    )

    output_dir = _resolve(
        cfg.get("output_dir", "ml/time/checkpoints/rubert_time"),
        base=ROOT,
    )
    assert output_dir is not None
    best_dir = output_dir / "best"
    output_dir.mkdir(parents=True, exist_ok=True)

    cls_w = float(cfg.get("loss_cls_weight", 1.0))
    reg_w = float(cfg.get("loss_reg_weight", 1.0))
    beta = float(cfg.get("smooth_l1_beta", 1.0))
    bce = nn.BCEWithLogitsLoss()
    smooth = nn.SmoothL1Loss(beta=beta, reduction="none")
    max_grad_norm = float(cfg.get("max_grad_norm", 1.0))
    epochs = int(cfg.get("epochs", 4))
    patience = cfg.get("early_stopping_patience")
    patience_n = int(patience) if patience else None

    scaler = torch.amp.GradScaler("cuda", enabled=use_fp16)

    def compute_loss(batch: dict[str, Any], outputs: dict[str, torch.Tensor]) -> torch.Tensor:
        loss_has_from = bce(outputs["has_from_logit"], batch["has_from"])
        loss_has_to = bce(outputs["has_to_logit"], batch["has_to"])
        mask_from = batch["has_from"]
        mask_to = batch["has_to"]
        reg_from = smooth(outputs["from_offset"], batch["from_offset"]) * mask_from
        reg_to = smooth(outputs["to_offset"], batch["to_offset"]) * mask_to
        denom_from = mask_from.sum().clamp_min(1.0)
        denom_to = mask_to.sum().clamp_min(1.0)
        loss_reg = reg_from.sum() / denom_from + reg_to.sum() / denom_to
        return cls_w * (loss_has_from + loss_has_to) + reg_w * loss_reg

    @torch.no_grad()
    def evaluate(loader: DataLoader) -> dict[str, float]:
        model.eval()
        losses: list[float] = []
        y_from_true: list[int] = []
        y_from_pred: list[int] = []
        y_to_true: list[int] = []
        y_to_pred: list[int] = []
        mae_from: list[float] = []
        mae_to: list[float] = []
        for batch in loader:
            batch = {k: v.to(device) if torch.is_tensor(v) else v for k, v in batch.items()}
            with torch.amp.autocast("cuda", enabled=use_fp16):
                outputs = model(
                    input_ids=batch["input_ids"],
                    attention_mask=batch["attention_mask"],
                )
                loss = compute_loss(batch, outputs)
            losses.append(float(loss.item()))
            pred_from = (torch.sigmoid(outputs["has_from_logit"]) >= 0.5).long()
            pred_to = (torch.sigmoid(outputs["has_to_logit"]) >= 0.5).long()
            y_from_true.extend(batch["has_from"].long().cpu().tolist())
            y_from_pred.extend(pred_from.cpu().tolist())
            y_to_true.extend(batch["has_to"].long().cpu().tolist())
            y_to_pred.extend(pred_to.cpu().tolist())
            for i in range(batch["has_from"].shape[0]):
                if batch["has_from"][i] > 0.5:
                    mae_from.append(
                        abs(
                            float(outputs["from_offset"][i].item())
                            - float(batch["from_offset"][i].item())
                        )
                    )
                if batch["has_to"][i] > 0.5:
                    mae_to.append(
                        abs(
                            float(outputs["to_offset"][i].item())
                            - float(batch["to_offset"][i].item())
                        )
                    )
        return {
            "loss": float(np.mean(losses)) if losses else 0.0,
            "has_from_f1": float(f1_score(y_from_true, y_from_pred, zero_division=0)),
            "has_to_f1": float(f1_score(y_to_true, y_to_pred, zero_division=0)),
            "from_mae_hours": float(np.mean(mae_from)) if mae_from else 0.0,
            "to_mae_hours": float(np.mean(mae_to)) if mae_to else 0.0,
        }

    best_score = -1e9
    bad_epochs = 0
    history: list[dict[str, float]] = []

    for epoch in range(1, epochs + 1):
        model.train()
        running = 0.0
        n_batches = 0
        optimizer.zero_grad(set_to_none=True)
        for step, batch in enumerate(train_loader, start=1):
            batch = {k: v.to(device) if torch.is_tensor(v) else v for k, v in batch.items()}
            with torch.amp.autocast("cuda", enabled=use_fp16):
                outputs = model(
                    input_ids=batch["input_ids"],
                    attention_mask=batch["attention_mask"],
                )
                loss = compute_loss(batch, outputs)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm)
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad(set_to_none=True)
            running += float(loss.item())
            n_batches += 1
            if step % int(cfg.get("logging_steps", 20)) == 0:
                print(f"epoch={epoch} step={step} loss={loss.item():.4f}")

        train_loss = running / max(n_batches, 1)
        val_metrics = evaluate(val_loader)
        score = (
            val_metrics["has_from_f1"]
            + val_metrics["has_to_f1"]
            - 0.01 * (val_metrics["from_mae_hours"] + val_metrics["to_mae_hours"])
        )
        row = {
            "epoch": float(epoch),
            "train_loss": train_loss,
            **val_metrics,
            "score": score,
        }
        history.append(row)
        print(f"epoch={epoch} train_loss={train_loss:.4f} val={val_metrics} score={score:.4f}")

        if score > best_score:
            best_score = score
            bad_epochs = 0
            best_dir.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), best_dir / "pytorch_model.bin")
            tokenizer.save_pretrained(best_dir)
            (best_dir / "model_type.json").write_text(
                json.dumps(
                    {
                        "architecture": "TimeWindowMultiHead",
                        "base_model": model_name,
                        "heads": [
                            "has_from_logit",
                            "has_to_logit",
                            "from_offset",
                            "to_offset",
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"  saved best -> {best_dir}")
        else:
            bad_epochs += 1
            if patience_n is not None and bad_epochs >= patience_n:
                print(f"early stopping after {epoch} epochs")
                break

    report: dict[str, Any] = {
        "best_score": best_score,
        "history": history,
        "train_bounds": bound_counts(train_rows),
        "val_bounds": bound_counts(val_rows),
    }
    (output_dir / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if cfg.get("export_onnx", True) and (best_dir / "pytorch_model.bin").is_file():
        model.load_state_dict(
            torch.load(
                best_dir / "pytorch_model.bin",
                map_location="cpu",
                weights_only=True,
            )
        )
        model.to("cpu")
        onnx_path = _resolve(
            cfg.get("onnx_path", "ml/time/artifacts/time_window_model.onnx"),
            base=ROOT,
        )
        tok_dir = _resolve(
            cfg.get("tokenizer_dir", "ml/time/artifacts/tokenizer"),
            base=ROOT,
        )
        assert onnx_path is not None and tok_dir is not None
        export_onnx(
            model,
            tokenizer,
            onnx_path,
            tok_dir,
            max_length=max_length,
            base_model=model_name,
        )

    print(f"Best checkpoint -> {best_dir}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Train rubert time-window multi-head")
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
