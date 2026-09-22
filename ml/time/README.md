# time (KAN-19, окно активности)

Извлечение `active_from` / `active_to` относительно `reference` datetime.
Title/summary / importance — не этот каталог (см. `ml/classify/`, `parser_common`).

## Задача

```
текст + reference → has_from, has_to, from_offset_h, to_offset_h
                 → active_from / active_to (ISO на inference)
```

Подходит для объявлений ЖКХ («с 12 по 14 марта») и новостей с датами в тексте.

## Файлы

| файл | роль |
|------|------|
| [DATA.md](./DATA.md) | формат JSONL, null-bounds, чеклист |
| [MODEL.md](./MODEL.md) | мультиголова, offsets, артефакты |
| `config_torch.yaml` | гиперпараметры под 3060 4GB |
| `dataset_io.py` | load/write JSONL + offsets |
| `ru_window.py` | детерминированная разметка RU-окон |
| `build_train_from_sources.py` | bootstrap_events + чаты → train/val |
| `bootstrap_data.py` | legacy-синтетика → `bootstrap.jsonl` |
| `train_torch.py` | fine-tune → checkpoint → ONNX |
| `export_onnx.py` | re-export |

`data/train.jsonl` / `val.jsonl` — собираются скриптом (в git не коммитятся).

## Train

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e ".[ml]"

# 1) качественный датасет из реальных событий + чатов:
python ml/time/build_train_from_sources.py

# 2) обучение (берёт data/train.jsonl + data/val.jsonl):
python ml/time/train_torch.py --config ml/time/config_torch.yaml
```

Smoke-синтетика (опционально):

```bash
python ml/time/bootstrap_data.py
```

Re-export:

```bash
python ml/time/export_onnx.py --checkpoint ml/time/checkpoints/rubert_time/best
```

## Runtime

Inference в `src/parser_common/time_onnx.py` — **не** импортировать `ml/` из runtime.
Артефакты: `ml/time/artifacts/`.