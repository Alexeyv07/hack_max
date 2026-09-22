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
| `train.jsonl` | основной train (собирается скриптом, в git не лежит) |
| `val.jsonl` | фиксированный val (тот же скрипт) |
| `label_report.json` | статистика последней сборки |
| `bootstrap.jsonl` | старая синтетика из `bootstrap_data.py` (smoke) |

## Сборка качественного датасета (рекомендуется)

Источники:

1. `src/parser_common/data/bootstrap_events.jsonl.gz` (news + mc)
2. экспорты домовых чатов MAX (`messages.json`)
3. curated gold из чатов (ЖКХ-окна) + реалистичная синтетика (короткие горизонты)

```bash
python ml/time/build_train_from_sources.py
# опционально:
# python ml/time/build_train_from_sources.py --chat PATH --synthetic-n 1200
```

Пишет `train.jsonl` + `val.jsonl` + `label_report.json`.

Разметка:

- детерминированный парсер `ru_window.py` (паттерны `с … по …`, `DD.MM HH:MM`,
  `завтра с 9:30 до 17:00`, опрессовка `7-21 июля`, …);
- offsets клипаются до ±30 суток (`max_abs_offset_h=720`);
- отсекаются счета/тарифы/реклама без event-окна;
- conf ≥ 0.8.

Старый путь (`bootstrap_data.py`) остаётся для smoke; для обучения time
используйте `build_train_from_sources.py`.

## Объёмы (ориентир под rubert-tiny2 / RTX 3060 4GB)

| цель | строк | заметки |
|------|-------|---------|
| smoke пайплайна | ~200–400 | `bootstrap.jsonl` |
| качественный train | ~1–1.5k | real chat/mc/news + synth, offsets ≤ 30д |
| дальше | 3k+ | больше реальных объявлений ЖКХ с точными часами |

Баланс: не только «оба bound есть» — нужны примеры только `from`, только `to`, оба `null`.

## Откуда брать тексты

**ЖКХ / MC / чаты.** Плановые отключения, ремонты, «с … по …», «до конца недели».
`reference` = дата публикации / дата сообщения в чате.

**Локальные новости.** Перекрытия, мероприятия с датами в тексте.
Если в тексте нет окна — `active_from`/`active_to` = `null`.

**Синтетика (legacy smoke):**

```bash
python ml/time/bootstrap_data.py
# пишет только data/bootstrap.jsonl

python ml/time/bootstrap_data.py --merge-into-train
# append только новых текстов в train.jsonl (без overwrite)
```

`bootstrap_data.py` **никогда** не перезаписывает `train.jsonl`.
`build_train_from_sources.py` **перезаписывает** `train.jsonl` / `val.jsonl`.

## Чеклист перед train

- [ ] `python ml/time/build_train_from_sources.py` уже прогнан
- [ ] JSONL парсится (`dataset_io.load_jsonl`)
- [ ] у каждой строки валидный `reference` (timezone-aware предпочтительно)
- [ ] `active_*` либо `null`, либо ISO-8601, парсятся в datetime
- [ ] если оба bound заданы — `active_from <= active_to`
- [ ] есть примеры с null-границами
- [ ] `val.jsonl` рядом или `val_ratio` в конфиге
- [ ] `python ml/time/train_torch.py --config ml/time/config_torch.yaml`
