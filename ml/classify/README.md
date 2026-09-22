# classify (KAN-13)

Трёхклассовый importance + отдельный `disaster_flag`. Title/summary модель не трогает —
эвристика в `src/parser_common/text.py`.

## Классы и флаг

| importance | типичное содержимое | disaster_flag |
|------------|-------------------|---------------|
| 1 | срочная опасность (газ, пожар, насилие, активное затопление) | `true` только у городской ЧС |
| 2 | ЖКХ/быт: отключения, пустой лифт, перекрытия | почти всегда `false` |
| 3 | шум чата / афиша / завершённое без ограничений | `false` |

Критерии: [`criteria_categories.txt`](./criteria_categories.txt).  
`disaster_flag=true` ≠ «просто класс 1». City-feed пускает `importance=1` только при
`disaster_flag=true` (см. `events.weight`).

## Runtime

```
текст → ONNX rubert-tiny2 → keyword rules
```

Код: `src/parser_common/classify.py`. ML отдаёт только importance; флаг ЧС — keywords.
Rules: `disaster` → `urgent`(cat.1) → `important`(cat.2) → 3.
Пакет `ml/` из `src` не импортировать.

| уровень | модуль | артефакт |
|---------|--------|----------|
| ONNX | `model_onnx.py` | `artifacts/importance_model.onnx` + tokenizer |
| rules | `classify.py` + `rules.yaml` | keywords |

## Train (только torch + GPU)

| скрипт | выход |
|--------|--------|
| `build_train_from_sources.py` | `data/train.jsonl` + `val.jsonl` |
| `train_torch.py` | HF checkpoint → ONNX |
| `export_onnx.py` | re-export |
| `bootstrap_data.py` | legacy `data/bootstrap.jsonl` |
| `weak_label.py` | черновая разметка rules |
| `criteria_label.py` | детерминированная разметка по критериям |

Данные: [DATA.md](./DATA.md). Модель: [MODEL.md](./MODEL.md).

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e ".[ml]"

python ml/classify/build_train_from_sources.py
python ml/classify/train_torch.py --config ml/classify/config_torch.yaml
```

Проверка руками:

```bash
set PYTHONPATH=src
python scripts/classify_try.py
```

Дедуп / embeddings — KAN-19, не этот каталог.