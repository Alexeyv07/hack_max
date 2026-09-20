# Как обучить модели после разметки

Runtime уже готов: без артефактов time/dedup/classify работают fallback'и
(importance → rules; time → null; dedup → hash embeddings). После разметки:

```powershell
cd C:\Users\iosh\Projects\hack_max
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e ".[ml]"
python -m spacy download ru_core_news_md
set PYTHONPATH=src
```

## 1) Importance (classify)

Формат: `ml/classify/DATA.md`  
Положи `ml/classify/data/train.jsonl`.

```powershell
python ml/classify/bootstrap_data.py
python ml/classify/train_torch.py --config ml/classify/config_torch.yaml
```

Артефакты: `ml/classify/artifacts/importance_model.onnx` (+ tokenizer, meta).

## 2) Time window (`active_from` / `active_to`)

Формат: `ml/time/DATA.md`  
Положи `ml/time/data/train.jsonl` (reference + ISO даты или null).

```powershell
python ml/time/bootstrap_data.py
python ml/time/train_torch.py --config ml/time/config_torch.yaml
```

Артефакты: `ml/time/artifacts/time_window_model.onnx` (+ tokenizer, meta).

## 3) Dedup thresholds

Формат пар: `ml/dedup/DATA.md`  
Положи `ml/dedup/data/pairs.jsonl` (`duplicate` | `update` | `unrelated`).

```powershell
python ml/dedup/bootstrap_pairs.py
python ml/dedup/eval_threshold.py --config ml/dedup/config.yaml
```

Скопируй найденные `duplicate_threshold` / `update_threshold` в `conf/local.yaml`
и `conf/prod.yaml` → секция `ml_dedup`.

Экспорт ONNX encoder (для Docker / prod без torch в runtime):

```powershell
python ml/dedup/export_onnx.py
# → ml/dedup/artifacts/embed_model.onnx (+ tokenizer, meta)
```

## 4) Миграция + прогон

```powershell
alembic upgrade head
python -m pytest tests/ml_dedup tests/parser_common -q
python -m main
```

Place NER: spaCy `ru_core_news_md` → spans → `StreetCatalog` / addresses.
Без модели spaCy остаётся catalog/matcher fallback.
