"""
# AGENTS.md — гайд для агентов и разработчиков

## Продукт

Бот + WebApp «Умный город» для мессенджера Max: чаты соседей, события рядом/по городу, уведомления.

## Структура модулей (`src/`)

Каждый доменный модуль (как `auth`, `events`) держит слои раздельно:

| Слой | Назначение |
|------|------------|
| `models/` | доменные dataclass / enum (не ORM) |
| `db/` | SQLAlchemy ORM (`*Row`) |
| `handlers/` | бизнес-логика + запросы к БД; **можно вызывать из других модулей** |
| `api/` | только HTTP (FastAPI): схемы, deps, routes → handlers |
| `commands/` | (бот) тонкая обёртка Max-событий → handlers |

**Запрещено:** класть SQL/бизнес-логику в `api/` или `commands/`.

## Точка входа

- `main.py` — один процесс: опционально API + Max-бот (`asyncio.gather`).
- `max.py` — `run_max_bot()`.
- `events/api/server.py` — `run_api_server()` (uvicorn Server **в том же процессе**, не отдельный OS-process).

Включение сервисов — `conf/*.yaml` → `runtime.enable_bot` / `runtime.enable_api`
(или env `ENABLE_BOT` / `ENABLE_API`). Для отладки можно закомментировать `create_task` в `main.py`.

## Parser common (KAN-13)

Библиотека середины пайплайна. **Не** ходит в источники и **не** является воркером.

```
парсер-воркер (KAN-10/11/12)          parser_common                 events
─────────────────────────────         ──────────────                ──────
fetch → ParserCandidate  ──normalize──▶ EventDraft
                         ──persist_candidate / to_event_create──▶ create_event → DB
```

- Title/body: эвристика (`text.py`), не LLM.
- Importance: ONNX → rules (`classify.py`, `ml/classify/MODEL.md`).
  `importance` и `disaster_flag` независимы (ML → класс; ЧС → keywords).
- Geo: опциональный `GeoMatcher` (KAN-6), не LLM.
- Дедуп — KAN-19 (хук около `create_event`), не здесь.
- Контракт для авторов парсеров: `src/parser_common/README.md`.
- Обучение: `ml/classify/train_torch.py` (GPU). Пакет `ml/` из `src` не импортировать.
- Ручной прогон classify: `python scripts/classify_try.py` (`PYTHONPATH=src`).
- Docker bot: extra `ml-runtime` (onnxruntime + transformers); веса из
  `ml/classify/artifacts` копируются в образ и монтируются в compose.

## News parser (KAN-11)

Модуль `src/parse_news/` — воркер новостных RSS/HTML-источников.

```
sources → RawNewsArticle → ParserCandidate → persist_candidate → events
```

- **6 outlets:** tass, ria (`ria.ru` export RSS), kommersant `/rubric/6`, msk1, mskagency, m24.
- **Restart-safe:** таблица `news_parser_cursors`; unique `(source, source_msg_id)` на `events`.
- **Режимы** (`news_parser.mode`):
  - `bootstrap` — только RSS/incremental (без HTML-архивов), лимит `bootstrap_articles_per_source`;
    после первого круга dump в `bootstrap_events.jsonl.gz`. **Не** делает 21d backfill.
  - `production` — полный backfill до `lookback_days` (обычно 21), затем incremental.
- **Geo:** только Москва. Каскад `resolve_article_geo` → `address_id` + `geo_by`
  (`city`|`street`|`home`):
  1) гео-поля источника; 2) текст (индекс / **StreetCatalog** stem+fuzzy / город);
  3) дефолт Москва **только** у локальных СМИ (`m24`/`msk1`/`mskagency`).
  Федеральные (`tass`/`ria`/`kommersant`) без явного московского места → `address_id=null`.
  Чужой город/страна → `null` (без подстановки Москвы). Без адреса событие **не в ленте**.
- **Лимит:** `max_articles_per_source_per_run` + `max_pages_per_run`;
  `collect_timeout_seconds` — таймаут одного `collect` на outlet.
  Вставка батчами `insert_batch_size`.
- **ТАСС:** sitemap часто 403 → Google News RSS `site:tass.ru when:Nd`.
- **Запуск:** `run_news_parser()` в `main.py` рядом с bot/api (supervised task).
- **Smoke live:** `python scripts/smoke_news_collect.py` (`PYTHONPATH=src`) —
  incremental, 1 страница по каждому enabled outlet.
- Контракт: `src/parse_news/README.md`. Миграции: курсоры, addresses components,
  `events.geo_by` / `published_at`.

KAN-10 (чаты) и KAN-12 — отдельные воркеры; общая середина — `parser_common` (KAN-13).

## Events (KAN-14)

- Финальные события в таблице `events` (не сырые кандидаты парсеров).
- **HTTP только чтение** для webapp; идентификация: заголовок `X-Max-User-Id` (тот же Max user, что знает бот).
  - `GET /events/feed?scope=nearby|city&cursor=&limit=` — TikTok-лента; гео из **чатов пользователя**, не из query.
  - `GET /events/map?limit=` — точки карты по чатам пользователя.
- Запись событий — **только handlers in-process** (`create_event` / …).
- **Чаты (KAN-5):** `chat_link.handlers.list_memberships_for_user` пока **MOCK** (один демо-чат, если user есть в `users` после `/start`).
- Шкала `importance`: `1` высокий приоритет, `2` важное, `3` бытовуха (не на карту).
- `disaster_flag` — отдельный признак ЧС, не алиас класса 1.
- `image_url` — главная фотка; `null` → фронт рисует карту с меткой.
- Гео события: `events.address_id -> addresses.id` + `events.geo_by`
  (`city`|`street`|`home`); `lat/lon` для API из `Address`, в `events` не дублируются.
  В `addresses` — компоненты `city` / `street` / `house`.
- City feed: `importance=1` только с `disaster_flag=true`.
- Map: `importance` 1–2; `category`: `catastrophe` | `important`.
- Вес ленты: `0.5×relevance + 0.3×timeliness + 0.2×source_reliability`
  (`events.weight`); reliability — в `news_parser.sources.*.reliability`.
- Дедуп (KAN-19) — хук в `create_event`.

## Конфиг

- `APP_ENVIRONMENT=local|prod` → `conf/local.yaml` / `conf/prod.yaml`.
- Секреты только в `.env` (`MAX_BOT_TOKEN`, пароли, ключи LLM).
- Env перекрывает YAML (`DATABASE_HOST`, `API_PORT`, …).

## Команды

```bash
pip install -e ".[dev]"
set PYTHONPATH=src
alembic upgrade head
python -m main

# ML classify (KAN-13), отдельно от runtime:
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e ".[ml]"
python ml/classify/train_torch.py --config ml/classify/config_torch.yaml
# данные: ml/classify/DATA.md
# ручные утилиты:
#   set PYTHONPATH=src & python scripts/classify_try.py
#   set PYTHONPATH=src & python scripts/smoke_news_collect.py

pytest
ruff check src tests
ruff format src tests
```

API локально: `http://localhost:8000/docs`, health: `/health`.

## Тесты

- `tests/` + pytest; API через `TestClient` и in-memory SQLite.
- Не требуют живой Postgres / Max token.
- При добавлении ORM — импорт в `alembic/env.py` и `tests/conftest.py` metadata.

## Стиль

- Python 3.12+, `from __future__ import annotations`.
- Коммиты: `FEAT:`, `FIX:`, `REFACTOR:`, `DOCS:`, `TEST:`.
- Ветки от `main`, PR в `main`.
