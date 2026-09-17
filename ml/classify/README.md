# classify (KAN-13)

Трёхклассовый importance + отдельный `disaster_flag`. Title/summary модель не трогает —
эвристика в `src/parser_common/text.py`.

## Классы и флаг

| importance | типичное содержимое | disaster_flag |
|------------|-------------------|---------------|
| 1 | критичный приоритет ленты | `true` только если это ЧС; иначе `false` |
| 2 | ЖКХ, локальные аварии, перекрытия | почти всегда `false` |
| 3 | шум чата / афиша / реклама | `false` |

`disaster_flag=true` ≠ «просто класс 1». City-feed пускает `importance=1` только при
`disaster_flag=true` (см. `events.weight`).

## Runtime

```
текст → ONNX rubert-tiny2 → keyword rules
```

Код: `src/parser_common/classify.py`. ML отдаёт только importance; флаг ЧС — keywords.
Пакет `ml/` из `src` не импортировать.

| уровень | модуль | артефакт |
|---------|--------|----------|
| ONNX | `model_onnx.py` | `artifacts/importance_model.onnx` + tokenizer |
| rules | `classify.py` + `rules.yaml` | keywords |

## Train (только torch + GPU)

| скрипт | выход |
|--------|--------|
| `train_torch.py` | HF checkpoint → ONNX |
| `export_onnx.py` | re-export |
| `bootstrap_data.py` | `data/bootstrap.jsonl` (не `train.jsonl`) |
| `weak_label.py` | черновая разметка |

Данные: [DATA.md](./DATA.md). Модель: [MODEL.md](./MODEL.md).

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e ".[ml]"
python ml/classify/train_torch.py --config ml/classify/config_torch.yaml
```

Проверка руками:

```bash
set PYTHONPATH=src
python scripts/classify_try.py
```

Дедуп / embeddings — KAN-19, не этот каталог.
