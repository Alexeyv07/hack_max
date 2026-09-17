# parse_news (KAN-11)

Воркер новостных источников: fetch → `RawNewsArticle` → `ParserCandidate` → `persist_candidate` → `events`.

## Поток

```text
источник (RSS / HTML listing)
        │
        ▼
  RawNewsArticle           # outlet, external_id, url, title, published_at, body?
        │
        ├─ resolve_article_address (только 6-значный индекс + GeoMatcher)
        ▼
  ParserCandidate          # source=news, source_msg_id=outlet:external_id
        │
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

## Backfill и курсоры

Таблица `news_parser_cursors` (ключ = outlet):

- **Первый запуск** или `backfill_complete=false` → `mode=backfill`, окно `lookback_days` (по умолчанию 21).
- **Incremental** после завершения backfill: RSS / первая страница ленты.
- **Restart-safe**: `listing_cursor` сохраняется между poll-циклами; при рестарте backfill продолжается с сохранённой страницы.
- Если `backfill_complete=true`, но событий outlet в `events` нет — снова backfill.

## Гео

`address_id` выставляется только если в title/body есть **6-значный почтовый индекс** и `GeoMatcher` нашёл адрес **не через fallback**. Иначе `address_id=null`.

## Конфиг

`conf/*.yaml` → секция `news_parser`:

- `runtime.enable_news_parser` / env `ENABLE_NEWS_PARSER`
- `lookback_days`, `poll_interval_seconds`, `max_articles_per_source_per_run`, …
- `sources.<outlet>.enabled`, `feed_url`, `listing_url`, …

Включение: `main.py` запускает `run_news_parser()` рядом с ботом/API (`asyncio.gather`).

## Тесты

Фикстуры без сети: `tests/parse_news/fixtures/`. Запуск:

```bash
set PYTHONPATH=src
pytest tests/parse_news -q
```
