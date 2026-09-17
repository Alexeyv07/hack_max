# Importance classify — данные

Формат строки JSONL:

```json
{"text": "Отключили воду на Лесной до вечера", "importance": 2, "disaster_flag": false, "source": "chat"}
```

| поле | обязательно | смысл |
|------|-------------|--------|
| `text` | да | сырой пост/новость |
| `importance` | да | `1` высокий приоритет, `2` важное ЖКХ/муниципалка, `3` шум |
| `disaster_flag` | нет (default `false`) | отдельный признак ЧС; **не** синоним `importance==1` |
| `source` | нет | `chat` / `news` / `public` / `synthetic` |

Файлы в `ml/classify/data/` (в gitignore):

| файл | роль |
|------|------|
| `train.jsonl` | ручная + собранная разметка (основной train) |
| `bootstrap.jsonl` | синтетика из `bootstrap_data.py` |
| `val.jsonl` / `test.jsonl` | опционально; иначе split в train-скриптах |

## importance vs disaster_flag

Это два поля, не одно.

- `importance=1` без `disaster_flag` — критично для ленты, но не городская ЧС (city-feed такие режет).
- `disaster_flag=true` — реальная ЧС (землетрясение, теракт, хим. авария, массовая эвакуация…). Обычно рядом стоит `importance=1`, но схема это не требует.
- Отключение воды / локальный пожар / прорыв трубы → `importance=2`, `disaster_flag=false`.
- Кошки, объявления, афиша → `3`, `false`.

Ошибки разметки, которые уже ловили: ЖКХ в класс 1, локальный пожар с `disaster_flag=true`, криминальная хроника как ЧС.

## Объёмы (ориентир под rubert-tiny2 / 3060 4GB)

| цель | строк | баланс |
|------|-------|--------|
| smoke пайплайна | ~300 | можно `bootstrap.jsonl` |
| хакатон-MVP | 1.5–3k | не хуже ~1:2:2 по классам |
| дальше | 5k+ | лучше quality-pass, чем сырой объём |

Класс 1 редкий — не добивать бытовухой; oversample / `class_weight` ок.

## Откуда брать тексты

**Чаты.** Выгрузка → `weak_label.py` → ручной проход по всем `importance=1` и `disaster_flag=true`, плюс выборка остального.

**Локальные СМИ / RSS.** ЧС → флаг + обычно класс 1; ЖКХ → 2; афиша → 3.

**Синтетика.**

```bash
python ml/classify/bootstrap_data.py
# пишет только data/bootstrap.jsonl

# если нужно докинуть недостающие шаблоны в train — append, без overwrite:
python ml/classify/bootstrap_data.py --merge-into-train
```

`bootstrap_data.py` **никогда** не перезаписывает `train.jsonl`.

## Чеклист перед train

- [ ] JSONL парсится (`dataset_io.load_jsonl`)
- [ ] есть все три класса
- [ ] `disaster_flag` проставлен явно там, где ЧС (не надеяться на «класс 1 = ЧС»)
- [ ] мало copy-paste дублей
- [ ] val отдельно или auto-split в конфиге
