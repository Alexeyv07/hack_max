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
  thresholds.json          # результат eval_threshold (опционально)
  # embedding ONNX — см. export_onnx.py (stub / будущий экспорт)
```

Runtime (src) читает пороги из конфига приложения; этот каталог — train/eval only.
Пакет `ml/` из `src` **не** импортировать.

## Fallback без transformers

`eval_threshold.py` умеет **hash-bag embedding** (символьные n-gram → нормированный
вектор), если torch/transformers недоступны. Только для smoke логики порогов,
не для продакшен-метрик.

## Метрики eval

- macro-F1 по трём классам при выбранных порогах;
- отдельно F1(`duplicate`), F1(`update`);
- confusion matrix в stdout / JSON.
