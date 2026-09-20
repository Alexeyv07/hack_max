# dedup (KAN-19)

Embeddings + пороги cosine для отношений пар: `duplicate` | `update` | `unrelated`.

## Файлы

| файл | роль |
|------|------|
| [DATA.md](./DATA.md) | формат пар JSONL |
| [MODEL.md](./MODEL.md) | mean-pool rubert-tiny2, пороги, contrastive later |
| `config.yaml` | дефолтные пороги и сетка поиска |
| `bootstrap_pairs.py` | синтетика → `data/bootstrap_pairs.jsonl` |
| `eval_threshold.py` | embed + grid search порогов |
| `export_onnx.py` | pretrained rubert → `artifacts/embed_model.onnx` |

`data/pairs.jsonl` — user-supplied. Каталог: `data/.gitkeep`.

## Eval / подбор порогов

```bash
pip install -e ".[ml]"   # transformers + torch желательны

python ml/dedup/bootstrap_pairs.py

python ml/dedup/eval_threshold.py \
  --pairs ml/dedup/data/bootstrap_pairs.jsonl \
  --config ml/dedup/config.yaml \
  --out ml/dedup/artifacts/thresholds.json
```

Скопируй `recommended.*` из `thresholds.json` в `conf/local.yaml` / `prod.yaml`
(`ml_dedup.duplicate_threshold` / `update_threshold`).

Без GPU/transformers скрипт уйдёт в hash-fallback (smoke).

## Экспорт ONNX (для Docker / prod без torch)

```bash
python ml/dedup/export_onnx.py
# → ml/dedup/artifacts/embed_model.onnx (+ meta + tokenizer)
```

Runtime читает этот файл первым; иначе transformers; иначе hash.

## Runtime

Inference и хук дедупа — в `src/ml_dedup/` (KAN-19). Сюда только данные,
пороги и ONNX encoder.
