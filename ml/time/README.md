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
| `bootstrap_data.py` | синтетика MC/news → `bootstrap.jsonl` |
| `train_torch.py` | fine-tune → checkpoint → ONNX |
| `export_onnx.py` | re-export |

`data/train.jsonl` — **user-supplied** (в git не коммитится). Рядом
`data/.gitkeep`, чтобы каталог существовал.

## Train

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e ".[ml]"

# синтетика для smoke (train.jsonl не трогает):
python ml/time/bootstrap_data.py

# скопировать bootstrap → train вручную или:
# copy ml\time\data\bootstrap.jsonl ml\time\data\train.jsonl
# либо append недостающих шаблонов:
python ml/time/bootstrap_data.py --merge-into-train

python ml/time/train_torch.py --config ml/time/config_torch.yaml
```

Re-export:

```bash
python ml/time/export_onnx.py --checkpoint ml/time/checkpoints/rubert_time/best
```

## Runtime

Код inference в `src/` появится отдельно — **не** импортировать `ml/` из runtime.
Артефакты: `ml/time/artifacts/`.
