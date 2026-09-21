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

Включение сервисов — `conf/*.yaml` → `runtime.enable_bot` / `runtime.enable_api` /
`runtime.enable_news_parser` / `runtime.enable_mc_parser`
(или env `ENABLE_BOT` / `ENABLE_API` / `ENABLE_NEWS_PARSER` / `ENABLE_MC_PARSER`).
Для отладки можно закомментировать `create_task` в `main.py`.

## Parser common (KAN-13)

Библиотека середины пайплайна. **Не** ходит в источники и **не** является воркером.

```
парсер-воркер (KAN-10/11/12/28)   parser_common              ml_dedup (KAN-19)     events
─────────────────────────────   ──────────────            ─────────────────     ──────
fetch → ParserCandidate ─normalize─▶ EventDraft ──resolve──▶ NEW|DUP|UPDATE ──▶ DB
                         persist_candidate (normalize+dedup+write)
```

- Title/body: эвристика (`text.py`), не LLM.
- Importance: ONNX → rules (`classify.py`, `ml/classify/MODEL.md`).
  `importance` и `disaster_flag` независимы (ML → класс; ЧС → keywords).
- **Time window** `active_from` / `active_to`: только ML ONNX
  (`time_extract.py` / `ml/time/`) — keyword-rules **не** используем.
- **Место**: spaCy NER → `StreetCatalog` / `GeoMatcher` → `addresses`
  (`place_ner.py`); без spaCy — catalog/matcher fallback.
- Scrape HTML/RSS: `parser_common.scrape` / `html_util` / `rss` / `body_text` /
  `http` — общие для всех воркеров (не импортировать между parse_*).
- Snapshot событий (все sources): `parser_common.seed`
  (`python -m parser_common.seed dump|load` →
  `src/parser_common/data/bootstrap_events.jsonl.gz`).
- **Дедуп (KAN-19):** `ml_dedup` внутри `persist_candidate` —
  NEW / DUPLICATE / UPDATE; окно активности `ml_dedup.active_days` (21).
- Контракт для авторов парсеров: `src/parser_common/README.md`.
- Обучение: `ml/classify/`, `ml/time/`, `ml/dedup/` (GPU). Пакет `ml/` из `src`
  не импортировать.
- Ручной прогон classify: `python scripts/classify_try.py` (`PYTHONPATH=src`).
- Docker bot: extra `ml-runtime` (onnxruntime + transformers + spacy); веса из
  `ml/*/artifacts` копируются в образ и монтируются в compose.

## News parser (KAN-11)

Модуль `src/parse_news/` — воркер новостных RSS/HTML-источников.

```
sources → RawNewsArticle → ParserCandidate → persist_candidate → events
```

- **6 outlets:** tass, ria (`ria.ru` export RSS), kommersant `/rubric/6`, msk1, mskagency, m24.
- **Restart-safe:** таблица `news_parser_cursors`; unique `(source, source_msg_id)` на `events`.
- **Режимы** (`news_parser.mode`):
  - `bootstrap` / `production` — оба делают **backfill до `lookback_days`**, затем incremental;
    bootstrap после завершения ещё пишет `bootstrap_events.jsonl.gz`.
  - `bootstrap_articles_per_source: 0` — без потолка (весь lookback); `>0` — soft-cap на outlet.
- **Geo:** только Москва. Каскад `resolve_article_geo` → `address_id` + `geo_by`
  (`city`|`street`|`home`):
  1) гео-поля источника; 2) текст (индекс / **StreetCatalog** stem+fuzzy / город);
  3) дефолт Москва **только** у локальных СМИ (`m24`/`msk1`/`mskagency`).
  Федеральные (`tass`/`ria`/`kommersant`) без явного московского места → `address_id=null`.
  Чужой город РФ → `null`. **Иностранные государства/области — статья не пишется в events**
  (не новостник по Украине/СНГ/дальнему зарубежью).
- **Лимит:** `max_articles_per_source_per_run` + `max_pages_per_run`;
  `collect_timeout_seconds` — таймаут одного `collect` на outlet.
  Вставка батчами `insert_batch_size`.
- **ТАСС:** sitemap часто 403 → Google News RSS `site:tass.ru when:Nd`.
- **Запуск:** `run_news_parser()` в `main.py` рядом с bot/api (supervised task).
- **Smoke live:** `python scripts/smoke_parser_collect.py` (`PYTHONPATH=src`) —
  `--parser news|mc|all`, опционально `--outlet`.
- Контракт: `src/parse_news/README.md`. Миграции: курсоры, addresses components,
  `events.geo_by` / `published_at`.

KAN-10 (чаты) и KAN-12 — отдельные воркеры; общая середина — `parser_common` (KAN-13).

## MC parser / ЖЭК (KAN-28)

Модуль `src/parse_mc/` — воркер сайтов управляющих компаний и ЖКХ-источников Москвы.

```
sources → RawMcNotice → resolve_notice_geos (все улицы) → ParserCandidate → events
```

- **5 outlets:** `pik_comfort` (ПИК-Комфорт), `granel` (ГранельЖКХ),
  `zhil_nagatino` (ГБУ «Жилищник» Нагатино-Садовники), `gbu_portal`
  (портал Жилищник), `moek` (МОЭК — тепло/отключения).
- **Fan-out:** если объявление затрагивает несколько улиц — **отдельное событие
  на каждую** (`source_msg_id` …`:addr:{address_id}`); `source=mc`.
- **Restart-safe:** таблица `mc_parser_cursors`; unique `(source, source_msg_id)`.
- Режимы как у news: `bootstrap` / `production`, `lookback_days`, soft-cap.
- **Запуск:** `run_mc_parser()` в `main.py` (`runtime.enable_mc_parser` /
  `ENABLE_MC_PARSER`).
- Smoke: `python scripts/smoke_parser_collect.py --parser mc`.
- Контракт: `src/parse_mc/README.md`. Миграция: `0010_mc_parser`.

Общий scrape/geo-text/seed — в `parser_common` (парсеры **не** импортируют друг друга).

## Events (KAN-14)

- Финальные события в таблице `events` (не сырые кандидаты парсеров).
- **HTTP только чтение** для webapp; идентификация: заголовок `X-Max-User-Id`
  (фронт берёт id из Max Bridge `initDataUnsafe.user.id`).
  - `GET /events/feed?scope=nearby|city&cursor=&limit=` — TikTok-лента.
  - `GET /events/map?limit=` — точки карты.
- Лента/карта **общие для всех** (без фильтра по чатам пользователя).
- В ленту попадают **только** события с `address_id` и непустым `Address.address_text`.
- **Правила ленты:** `importance` 1|2 (`3` не в nearby и не в city); сортировка по
  `events.weight` DESC; nearby — `geo_by` ∈ {`street`,`home`}; city — `geo_by=city`
  (персонализация по чатам — позже).
- Ответ feed item: `title`, `body`, `importance`, `disaster_flag`, `image_url`,
  `source` / `source_url`, `location` (текст адреса), `published_at` / `created_at`,
  `lat`/`lon`, `geo_by`, `weight`.
- Запись событий — **только handlers in-process** (`create_event` / …).
- **Чаты (KAN-5):** модуль `user_chat`, таблицы `chats` + `users_chat`. `list_memberships_for_user` читает реальное членство и координаты из `Address`; `/start` сам по себе не добавляет пользователя в чат. Контракт: `src/user_chat/README.md`.
- **Подключение чата (KAN-7):** `chat_link` — onboarding и оркестрация реального MAX group chat;
  хранение `chats`/`users_chat` — `user_chat`, адресный snapshot — `address.StreetCatalog`.
  4 способа адреса: bot-picker `город → район → улица → дом`, индекс, карта и текст в WebApp.
  Callback-flow редактирует один bot-screen; списки не делают SQL на каждый callback.
- Шкала `importance`: `1` высокий приоритет, `2` важное, `3` бытовуха (не на карту и не в ленты).
- `disaster_flag` — отдельный признак ЧС, не алиас класса 1.
- `image_url` — главная фотка; `null` → фронт рисует чёрный плейсхолдер (карта — KAN-17).
- Гео события: `events.address_id -> addresses.id` + `events.geo_by`
  (`city`|`street`|`home`); `lat/lon` для API из `Address`, в `events` не дублируются.
  В `addresses` — компоненты `city` / `district` / `street` / `house`.
- Окно действия: `events.active_from` / `events.active_to` (ML time-window).
- Map: `importance` 1–2; `category`: `catastrophe` | `important`.
- Вес ленты: `0.5×relevance + 0.3×timeliness + 0.2×source_reliability`
  (`events.weight`); reliability — в `news_parser.sources.*.reliability`.
- Дедуп (KAN-19): `ml_dedup.resolve` в `persist_candidate` —
  DUPLICATE → не плодить; UPDATE → обновить активное событие (окно 21 день).

## WebApp (KAN-16)

- SvelteKit mini-app в `webapp/` (`adapter-static`): TikTok-лента nearby | city.
- Данные **только** с API (`GET /events/feed`) → БД.
- **Публикация:** GitHub Pages `https://alexeyv07.github.io/hack_max/` —
  workflow `.github/workflows/webapp-pages.yaml` на тег `v*` (или workflow_dispatch).
  Сборка: `BASE_PATH=/hack_max`, `PUBLIC_API_BASE` = repo var `WEBAPP_API_BASE`
  (публичный origin API без `/api`). Рядом на Pages лежит mdBook в `/docs/`.
- **Локально:** `npm run dev` → http://localhost:5173; `PUBLIC_API_BASE=/api`
  (Vite proxy → `API_PROXY_TARGET` / `:8000`). User id **не** из Bridge —
  фейковый `159064979` на hostname `localhost` / `127.0.0.1`.
- **На Pages / в Max:** user id из Max Bridge
  (`window.WebApp.initDataUnsafe.user.id` / initData / hash) → заголовок
  `X-Max-User-Id`.
- CORS: `api.cors_origins` в conf (вкл. `https://alexeyv07.github.io`) или
  `API_CORS_ORIGINS`.
- UI: full-height snap-карточки, табы «Новости рядом / города», свайп вправо → город,
  картинка с lightbox, цветовая полоса по importance, SVG при `disaster_flag`,
  дата / источник (ссылка) / локация в одну строку; длинный body — синяя ссылка «ещё»,
  прокрутка текста только после раскрытия.

### Кнопка webapp в боте

- Приветствие (`bot_started` / `/start`) шлёт inline-кнопку типа **`open_app`**
  (`OpenAppButton`, текст «Открыть новости»).
- Мини-приложение привязывается к боту на платформе MAX
  ([docs/webapps](https://dev.max.ru/docs/webapps/introduction)): HTTPS URL =
  GitHub Pages (`https://alexeyv07.github.io/hack_max/`).
- Identity кнопки: `GET /me` → `web_app` (username) + `contact_id`.

## Конфиг

- `APP_ENVIRONMENT=local|prod` → `conf/local.yaml` / `conf/prod.yaml`.
- Секреты только в `.env` (`MAX_BOT_TOKEN`, пароли, ключи LLM).
- Env перекрывает YAML (`DATABASE_HOST`, `API_PORT`, `API_CORS_ORIGINS`, …).

## Команды

```bash
pip install -e ".[dev]"
set PYTHONPATH=src
alembic upgrade head
python -m main

# WebApp (KAN-16), в другом терминале — данные с API/БД:
# cd webapp && npm install && npm run dev
# → http://localhost:5173  (прокси /api → :8000; user_id=159064979)

# ML classify (KAN-13), отдельно от runtime:
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e ".[ml]"
python ml/classify/train_torch.py --config ml/classify/config_torch.yaml
# данные: ml/classify/DATA.md
# ручные утилиты:
#   set PYTHONPATH=src & python scripts/classify_try.py
#   set PYTHONPATH=src & python scripts/smoke_parser_collect.py

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
