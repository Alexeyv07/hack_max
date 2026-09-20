# Модель dedup (embeddings + пороги)

## Подход (MVP)

1. **Encoder:** pretrained `cointegrated/rubert-tiny2` без fine-tune.
2. **Вектор:** mean-pooling по token embeddings с учётом `attention_mask`, L2-norm.
3. **Сходство:** cosine между `emb(text_a)` и `emb(text_b)`.
4. **Решение:** два порога на cosine:

```
sim >= dup_threshold      → duplicate
upd_threshold <= sim < dup → update
sim < upd_threshold       → unrelated
```

Требование: `dup_threshold >= update_threshold`.

Дефолты — в `config.yaml`; подбор — `eval_threshold.py` (grid search по F1
на парах `duplicate` vs остальное и `update` vs `unrelated`).

## Почему не классификатор сразу

- rubert-tiny2 embeddings уже разделяют близкие пересказы на русском.
- Пороги дешёвые в runtime (один encode на текст + кэш).
- Contrastive fine-tune — опциональный следующий шаг (не в MVP).

## Contrastive fine-tune (позже)

Если pretrained пороги не держат hard-negatives:

- пары `(anchor, positive=duplicate|update, negative=unrelated)`;
- InfoNCE / Triplet на mean-pool;
- затем снова grid search порогов на held-out.

Скрипт обучения пока не обязателен — зафиксировано здесь как направление.

## Артефакты

```
ml/dedup/artifacts/
  thresholds.json          # результат eval_threshold
  embed_model.onnx         # mean-pool + L2 (export_onnx.py)
  embed_model.meta.json
  tokenizer/
```

Экспорт ONNX (тот же pretrained, что eval):

```bash
python ml/dedup/export_onnx.py
# → ml/dedup/artifacts/embed_model.onnx
```

Runtime (`src/ml_dedup/embed.py`): ONNX → transformers → hash-fallback.
Пороги — из `conf/*.yaml` (`ml_dedup.*`), не из thresholds.json автоматически.


## Fallback без transformers

`eval_threshold.py` умеет **hash-bag embedding** (символьные n-gram → нормированный
вектор), если torch/transformers недоступны. Только для smoke логики порогов,
не для продакшен-метрик.

## Метрики eval

- macro-F1 по трём классам при выбранных порогах;
- отдельно F1(`duplicate`), F1(`update`);
- confusion matrix в stdout / JSON.
