# Time window — данные (`active_from` / `active_to`)

Извлечение окна активности события относительно опорной даты `reference`
(`published_at` источника или «сейчас» на момент разметки).

## Формат строки JSONL

```json
{
  "text": "Отключение горячей воды с 12 по 14 марта с 10:00 до 18:00",
  "active_from": "2026-03-12T10:00:00+03:00",
  "active_to": "2026-03-14T18:00:00+03:00",
  "reference": "2026-03-11T12:00:00+03:00",
  "source": "mc"
}
```

| поле | обязательно | смысл |
|------|-------------|--------|
| `text` | да | сырой текст объявления / новости |
| `reference` | да | ISO-8601 datetime — точка отсчёта offsets |
| `active_from` | нет (`null`) | начало окна; `null` = нижней границы нет / неизвестна |
| `active_to` | нет (`null`) | конец окна; `null` = верхней границы нет / неизвестна |
| `source` | нет | `mc` / `news` / `chat` / `synthetic` |

Оба bound могут быть `null` (событие без явного окна — только «сейчас/неизвестно»).
Один bound без другого — нормально (например, «с завтра» без конца).

## Целевые величины для модели

Модель **не** предсказывает ISO-строки напрямую. На train/infer:

| голова | тип | из разметки |
|--------|-----|-------------|
| `has_from` | binary | `active_from is not null` |
| `has_to` | binary | `active_to is not null` |
| `from_offset_hours` | float | `(active_from − reference)` в часах |
| `to_offset_hours` | float | `(active_to − reference)` в часах |

При inference: `active_* = reference + timedelta(hours=offset)` только если `has_*`.

Часовой пояс сохраняем у `reference`; offsets — абсолютные часы (могут быть дробными).

## Файлы в `ml/time/data/`

| файл | роль |
|------|------|
| `train.jsonl` | **пользовательская** разметка (основной train) — в git не лежит |
| `bootstrap.jsonl` | синтетика из `bootstrap_data.py` |
| `val.jsonl` / `test.jsonl` | опционально; иначе auto-split в `train_torch.py` |

`train.jsonl` — user-supplied. Скрипты **не** создают его автоматически
(кроме опционального `--merge-into-train`, который только **дописывает**).

## Объёмы (ориентир под rubert-tiny2 / RTX 3060 4GB)

| цель | строк | заметки |
|------|-------|---------|
| smoke пайплайна | ~200–400 | `bootstrap.jsonl` |
| хакатон-MVP | 1–2k | смесь MC (окна работ) + news (даты в тексте) |
| дальше | 3k+ | больше реальных объявлений ЖКХ с точными часами |

Баланс: не только «оба bound есть» — нужны примеры только `from`, только `to`, оба `null`.

## Откуда брать тексты

**ЖКХ / MC.** Плановые отключения, ремонты, «с … по …», «до конца недели».
`reference` = дата публикации объявления.

**Локальные новости.** Перекрытия, мероприятия с датами в тексте.
Если в тексте нет окна — `active_from`/`active_to` = `null`.

**Синтетика.**

```bash
python ml/time/bootstrap_data.py
# пишет только data/bootstrap.jsonl

python ml/time/bootstrap_data.py --merge-into-train
# append только новых текстов в train.jsonl (без overwrite)
```

`bootstrap_data.py` **никогда** не перезаписывает `train.jsonl`.

## Чеклист перед train

- [ ] JSONL парсится (`dataset_io.load_jsonl`)
- [ ] у каждой строки валидный `reference` (timezone-aware предпочтительно)
- [ ] `active_*` либо `null`, либо ISO-8601, парсятся в datetime
- [ ] если оба bound заданы — `active_from <= active_to`
- [ ] есть примеры с null-границами
- [ ] val отдельно или `val_ratio` в конфиге
