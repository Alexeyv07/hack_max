# Importance classify — данные

Формат строки JSONL:

```json
{"text": "Отключили воду на Лесной до вечера", "importance": 2, "disaster_flag": false, "source": "chat"}
```

| поле | обязательно | смысл |
|------|-------------|--------|
| `text` | да | сырой пост/новость |
| `importance` | да | `1` срочная опасность, `2` важно для быта, `3` информационное |
| `disaster_flag` | нет (default `false`) | городская ЧС; **не** синоним `importance==1` |
| `source` | нет | `chat` / `news` / `mc` / `curated` / `synthetic` |

Продуктовые критерии разметки: [`criteria_categories.txt`](./criteria_categories.txt)
(копия инструкции «Критерии категорий событий»). Кратко:

1. Сначала признаки **срочной опасности** (пожар/дым/газ/насилие/активное затопление…).
2. Иначе **важно для быта** (отключения, лифт пустой, перекрытие въезда…).
3. Иначе **информационное** (кот, афиша, потушенный пожар без ограничений…).
4. Неоднозначные фразы без контекста **не** класть в train как золото.

## importance vs disaster_flag

- `importance=1` + `disaster_flag=false` — локальная срочность (газ в подъезде, пожар в квартире).
- `importance=1` + `disaster_flag=true` — городская ЧС (землетрясение, режим ЧС, хим. авария…).
- Отключение воды / пустой лифт / перекрытие двора → `2`, `false`.
- Кошки, объявления, завершённое без последствий → `3`, `false`.

## Файлы в `ml/classify/data/`

| файл | роль |
|------|------|
| `train.jsonl` / `val.jsonl` | сборка `build_train_from_sources.py` |
| `label_report.json` | статистика последней сборки |
| `bootstrap.jsonl` | legacy-синтетика `bootstrap_data.py` |

## Сборка (рекомендуется)

```bash
python ml/classify/build_train_from_sources.py
# python ml/classify/build_train_from_sources.py --synthetic-n 900 --dry-run
```

Источники: `bootstrap_events.jsonl.gz` + чаты MAX + curated gold (§3–6 критериев)
+ синтетика под те же правила. Offsets/важность клипуются балансом классов.

## Объёмы

| цель | строк | баланс |
|------|-------|--------|
| smoke | ~300 | `bootstrap.jsonl` |
| качественный train | ~1.5–2.5k | class_weight=balanced; cat.1 не раздувать шумом |
| дальше | 5k+ | больше реальных chat/mc с ручным ревью cat.1 |

## Чеклист перед train

- [ ] `python ml/classify/build_train_from_sources.py`
- [ ] `pytest ml/classify/test_criteria_label.py`
- [ ] JSONL парсится (`dataset_io.load_jsonl`)
- [ ] есть все три класса; `disaster_flag` только у реальных ЧС
- [ ] `python ml/classify/train_torch.py --config ml/classify/config_torch.yaml`
