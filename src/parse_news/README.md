# parse_news (KAN-11)

Воркер новостных источников: fetch → `RawNewsArticle` → гео → `ParserCandidate` → `persist_candidate` → `events`.

## Режимы (`news_parser.mode`)

| mode | Назначение | Поведение |
|------|------------|-----------|
| `bootstrap` | Хакатон / демо | **Только RSS/incremental** (без HTML-архивов) → быстро; после первого круга dump в `bootstrap_events.jsonl.gz`. Критерий «~21 день истории» **не** применяется. |
| `production` | Боевой realtime | Полный backfill до `lookback_days`, затем incremental |

### Snapshot событий (как addresses)

```bash
# после успешного bootstrap (или вручную из БД):
set PYTHONPATH=src
python -m parse_news.seed dump
# → src/parse_news/data/bootstrap_events.jsonl.gz

# загрузка в пустую БД:
python -m parse_news.seed load
```

Docker entrypoint (`scripts/bot_entrypoint.py`): addresses seed → events snapshot → main.

## Геопривязка

Только **Москва**. Иностранные государства и их области **не создают события**
(воркер пропускает статью). Чужой город РФ / без места у федеральных СМИ →
`address_id=null` (нет в ленте).

- Локальные СМИ (`m24`/`msk1`/`mskagency`) без чужой гео → Москва city.
- Федеральные (`tass`/`ria`/`kommersant`) — только при явном «Москва» / улице / индексе.
- StreetCatalog: stemming + fuzzy; топонимы вроде «Днепропетровск» в hints не идут.

## Поток

```text
источник (RSS / HTML listing)
        │
        ▼
  RawNewsArticle           # + published_at, опционально geo_*
        ▼
  resolve_article_geo      # StreetCatalog stem+fuzzy → GeoBind
        ▼
  ParserCandidate → persist_candidate → events (weight, published_at, geo_by)
```

## Адаптеры (`sources/`)

| outlet | key | listing / feed |
|--------|-----|----------------|
| ТАСС | `tass` | RSS; backfill sitemap / Google News |
| РИА | `ria` | `ria.ru` export RSS; архив |
| Коммерсант | `kommersant` | `/rubric/6`, archive |
| MSK1 | `msk1` | RSS; listing `text/?page={page}` |
| МСК Агентство | `mskagency` | `/lenta?page=` |
| M24 | `m24` | RSS; walk ID |

У каждого outlet в YAML: `reliability` (0..1) для веса ленты.

## Вес в ленте (TikTok)

```text
weight = 0.50 × relevance + 0.30 × timeliness + 0.20 × source_reliability
```

- **relevance** — importance + близость к чату + точность `geo_by`
- **timeliness** — half-life 24ч от `published_at` (иначе `created_at`)
- **source_reliability** — `news_parser.sources.<outlet>.reliability`

Пересчёт с `distance_m` — при `GET /events/feed`.

## Конфиг

Числа ниже — **пример** (см. актуальные `conf/local.yaml` / `conf/prod.yaml`;
лимиты и таймауты часто меняются под демо/нагрузку):

```yaml
news_parser:
  mode: bootstrap          # или production
  bootstrap_articles_per_source: 15
  max_articles_per_source_per_run: 15
  max_pages_per_run: 1
  lookback_days: 21        # имеет смысл в production
  collect_timeout_seconds: 90
  poll_interval_seconds: 60
  sources.msk1.listing_url: "https://msk1.ru/text/?page={page}"
  sources.msk1.reliability: 0.82
```

## Smoke live

Проверка, что все enabled-адаптеры живы (сеть, 1 страница, без записи в БД):

```bash
set PYTHONPATH=src
python scripts/smoke_news_collect.py
# опционально: --outlet m24  или  RUN_LIVE_NEWS=1 pytest tests/parse_news/test_live_smoke.py -q
```

## Тесты (офлайн)

```bash
set PYTHONPATH=src
pytest tests/parse_news tests/events/test_weight.py -q
```
