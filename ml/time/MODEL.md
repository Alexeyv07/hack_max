# Модель time window (`active_from` / `active_to`)

## Что предсказываем

Мультиголовая сеть поверх encoder `cointegrated/rubert-tiny2`:

| голова | loss | смысл |
|--------|------|--------|
| `has_from` | BCEWithLogits | есть ли нижняя граница |
| `has_to` | BCEWithLogits | есть ли верхняя граница |
| `from_offset_hours` | SmoothL1 (masked) | offset от `reference`, часы |
| `to_offset_hours` | SmoothL1 (masked) | offset от `reference`, часы |

Regression-головы обучаются **только** на примерах, где соответствующий `has_*=1`
(mask в loss). Так модель не штрафуется за «мусорные» offsets при `null`.

## Почему offsets, а не ISO

- rubert-tiny2 маленький — регрессия по часам стабильнее генерации дат.
- Один `reference` на пример даёт относительную шкалу (завтра / через 3 дня /
  «с 10 до 18 сегодня»).
- На inference: `dt = reference + timedelta(hours=offset)`.

## Архитектура (train)

```
text → rubert-tiny2 → [CLS] hidden
  ├─ Linear → has_from (logit)
  ├─ Linear → has_to (logit)
  ├─ Linear → from_offset_hours
  └─ Linear → to_offset_hours
```

Общий encoder; головы — узкие Linear. На RTX 3060 4GB: batch 8–16, `fp16`,
`max_length` 128–192, 3–5 эпох.

## Артефакты

```
ml/time/artifacts/
  time_window_model.onnx
  time_window_model.meta.json
  tokenizer/                 # HF tokenizer files
```

Сборка: `train_torch.py` (после обучения зовёт export) или `export_onnx.py`.

Meta хранит `format`, `max_length`, имена выходов ONNX, шкалу offsets (`hours`).

## Train

- Конфиг: `config_torch.yaml`
- Скрипт: `train_torch.py` → checkpoint → ONNX
- Данные: `data/train.jsonl` (см. [DATA.md](./DATA.md))
- Синтетика: `bootstrap_data.py` → `bootstrap.jsonl` (train не перезаписывает)

Метрики на val: accuracy/`F1` по `has_*`, MAE по offsets на masked subset.

## Runtime (позже, в src)

Пакет `ml/` из `src` **не** импортировать. Runtime подхватит ONNX + tokenizer
из `artifacts/` отдельным модулем (KAN-19 / соседние тикеты) — не этот каталог.

## Ограничения

- Модель не парсит календарь «в лоб»: опирается на паттерны в тексте + reference.
- Очень длинные горизонты (месяцы+) — редкий хвост; при разметке лучше клипать
  или отдельный bucket (пока не делаем).
- Абсолютные даты без года в тексте требуют корректного `reference` (год/TZ).
