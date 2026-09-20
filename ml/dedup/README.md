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
| `export_onnx.py` | stub: как экспортировать embedding encoder |

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

Без GPU/transformers скрипт уйдёт в hash-fallback (smoke).

## Runtime

Inference и хук дедупа — в `src/` (KAN-19), не здесь. Сюда только данные,
пороги и (позже) экспорт encoder.
