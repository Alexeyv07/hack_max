# Модель importance (runtime + train)

## Что предсказываем

Softmax на 3 класса → `importance ∈ {1,2,3}`.

`disaster_flag` в runtime **не** голова сети: его ставят keyword-rules
(`classify.disaster_flag_by_rules`). В JSONL флаг размечается отдельно.

## Каскад

1. ONNX fine-tune `cointegrated/rubert-tiny2` (`predict_importance_onnx`)
2. Rules (`classify_by_rules`) — и importance, и флаг

Порог: `min_confidence` (default 0.45). Ниже → rules.

При срабатывании ONNX: `importance` из модели, `disaster_flag` из keywords.
Так возможны пары `(1, false)` и `(2, true)`.

## Артефакты

```
ml/classify/artifacts/
  importance_model.onnx
  importance_model.meta.json
  tokenizer/                 # HF tokenizer files
```

Сборка: `train_torch.py` (после обучения сам зовёт export) или `export_onnx.py`.

## Train

- Конфиг: `config_torch.yaml`
- Скрипт: `train_torch.py` → checkpoint → ONNX
- Данные: `data/train.jsonl`
- Синтетика: `bootstrap_data.py` → `bootstrap.jsonl` (train не перезаписывает)

GPU обязателен для нормального fine-tune (у нас RTX 3060 / CUDA).
На 3060 4GB: tiny2, batch 16–32, 3–5 эпох.

## Rules

Дефолты в `classify.py`, доп. список — `rules.yaml`.
Rules-only мапит disaster-keywords → `(1, true)` как fallback без модели.

## Ручная проверка

```bash
set PYTHONPATH=src
python scripts/classify_try.py
```

Показывает raw ONNX-probs, rules и итоговый каскад.
