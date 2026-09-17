# parse_news (KAN-11)

Воркер новостных источников: fetch → `RawNewsArticle` → гео → `ParserCandidate` → `persist_candidate` → `events`.

## Поток

```text
источник (RSS / HTML listing)
        │
        ▼
  RawNewsArticle           # outlet, external_id, url, title, published_at, body?
        │                  # опционально: geo_city / geo_street / geo_house
        ▼
  resolve_article_geo      # → GeoBind(address_id, geo_by)
        │
        ▼
  ParserCandidate          # source=news, source_msg_id=outlet:external_id
        │                  # address_id + geo_by
        ▼
  persist_candidate → events
```

## Адаптеры (`sources/`)

| outlet | key | listing / feed | ID из URL |
|--------|-----|----------------|-----------|
| ТАСС | `tass` | RSS `tass.ru/rss/v2.xml`; backfill: sitemap / Google News | `/1234567` в path |
| РИА | `ria` | RSS `ria.ru/export/rss2/index.xml`; backfill: дневной архив | `-2118199709.html` |
| Коммерсант | `kommersant` | `/rubric/6`, archive | `/doc/1234567` |
| MSK1 | `msk1` | RSS `msk1.ru/rss-feeds/rss.xml`; backfill: `/text/?page=` | `/text/.../YYYY/MM/DD/76634109/` |
| МСК Агентство | `mskagency` | `/lenta?page=` | `/materials/111`, `data-material_id` |
| M24 | `m24` | RSS `m24.ru/rss.xml`; backfill: walk по ID | `/news/DDMMYYYY/9876543` |

Контракт адаптера: `BaseNewsSource.collect(client, since, mode, listing_cursor, max_articles) → CollectResult`.

- `mode`: `backfill` | `incremental`
- `CollectResult`: `articles`, `next_cursor` (для пагинации backfill), `reached_since`
- Если источник отдаёт структурированное место — заполнить `RawNewsArticle.geo_*`

## Backfill и курсоры

Таблица `news_parser_cursors` (ключ = outlet):

- **Первый запуск** или `backfill_complete=false` → `mode=backfill`, окно `lookback_days` (по умолчанию 21).
- **Incremental** после завершения backfill: RSS / первая страница ленты.
- **Restart-safe**: `listing_cursor` сохраняется между poll-циклами; при рестарте backfill продолжается с сохранённой страницы.
- Если `backfill_complete=true`, но событий outlet в `events` нет — снова backfill.

## Геопривязка

Событие получает `address_id` + `geo_by` (`city` | `street` | `home`).

Справочник `addresses` хранит компоненты `city` / `street` / `house`. Сопоставление:

| Что известно | `geo_by` | Как выбирается адрес |
|--------------|----------|----------------------|
| город + улица + дом | `home` | точная строка в `addresses` |
| город + улица | `street` | любой дом на улице (пин на карте) |
| только город | `city` | city-адрес (street/house пустые; создаётся при необходимости) |

### Каскад `resolve_article_geo`

1. **Метаданные источника** — если адаптер заполнил `geo_city` / `geo_street` / `geo_house`, сразу `find_geo_bind`.
2. **Анализ текста** (title + body):
   - 6-значный индекс → `GeoMatcher` по домам индекса → обычно `geo_by=home`;
   - упоминание улицы (+ опционально дом) → сопоставление по `city/street/house`, иначе fuzzy по индексу улиц Москвы;
   - упоминание Москвы без улицы → `geo_by=city`.
3. **Дефолт по outlet** — локальные московские СМИ без места в тексте:
   - `m24`, `msk1`, `mskagency` → город Москва, `geo_by=city`;
   - федеральные (`ria`, `tass`, `kommersant`) → без дефолта, `address_id=null`.

Логика справочника и `find_geo_bind` — в `address.resolve` / `address.components`.

## Конфиг

`conf/*.yaml` → секция `news_parser`:

- `runtime.enable_news_parser` / env `ENABLE_NEWS_PARSER`
- `lookback_days`, `poll_interval_seconds`, `max_articles_per_source_per_run`, `insert_batch_size`, …
- `sources.<outlet>.enabled`, `feed_url`, `listing_url`, …

Включение: `main.py` запускает `run_news_parser()` рядом с ботом/API (`asyncio.gather`).

## Тесты

Фикстуры без сети: `tests/parse_news/fixtures/`. Запуск:

```bash
set PYTHONPATH=src
pytest tests/parse_news -q
```
