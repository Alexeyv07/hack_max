# Модель importance (runtime + train)

## Что предсказываем

Один softmax на 3 класса → `importance ∈ {1,2,3}`.

`disaster_flag` в runtime **не** голова сети: его ставят keyword-rules в `classify.disaster_flag_by_rules`. В JSONL флаг размечается отдельно и не пересчитывается из класса при загрузке (`dataset_io`).

Старые артефакты могли содержать `"disaster_is_importance_1": true` — поле игнорируется инференсом.

## Каскад

1. ONNX `cointegrated/rubert-tiny2` fine-tune (`predict_importance_onnx`)
2. TF-IDF + LogReg JSON (`predict_importance`)
3. Rules (`classify_by_rules`) — и importance, и флаг

Порог: `min_confidence` (default 0.45). Ниже → следующий уровень.

При срабатывании ONNX/TF-IDF: `importance` из модели, `disaster_flag` из rules-keywords по тому же тексту. Так возможны пары `(1, false)` и `(2, true)`.

## Артефакты

```
ml/classify/artifacts/
  importance_model.json      # tfidf_logreg_v1
  importance_model.onnx      # optional
  importance_model.meta.json
  tokenizer/                 # HF tokenizer files
```

Формат TF-IDF JSON: vocabulary, idf, coef, intercept, classes. Сборка — `train.py`.

## Train (torch)

- Конфиг: `config_torch.yaml`
- Скрипт: `train_torch.py` → checkpoint → `export_onnx.py`
- Данные: `data/train.jsonl` (+ опционально val). Синтетику см. `bootstrap_data.py` → `bootstrap.jsonl`.

На 3060 4GB: tiny2, batch 16–32, 3–5 эпох достаточно для MVP-объёма.

## Rules

Дефолты зашиты в `classify.py`, доп. список — `rules.yaml` (`disaster` / `important`). Rules-only путь по-прежнему мапит disaster-keywords → `(1, true)` как fallback без модели.
