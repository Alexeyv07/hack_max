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
- **Smoke live:** `python scripts/smoke_news_collect.py` (`PYTHONPATH=src`) —
  incremental, 1 страница по каждому enabled outlet.
- Контракт: `src/parse_news/README.md`. Миграции: курсоры, addresses components,
  `events.geo_by` / `published_at`.

KAN-10 (чаты) и KAN-12 — отдельные воркеры; общая середина — `parser_common` (KAN-13).

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
- **Подключение чата (KAN-7):** отдельный модуль `chat_link` для onboarding; хранение чатов и membership относится к `user_chat`.
- Шкала `importance`: `1` высокий приоритет, `2` важное, `3` бытовуха (не на карту и не в ленты).
- `disaster_flag` — отдельный признак ЧС, не алиас класса 1.
- `image_url` — главная фотка; `null` → фронт рисует чёрный плейсхолдер (карта — KAN-17).
- Гео события: `events.address_id -> addresses.id` + `events.geo_by`
  (`city`|`street`|`home`); `lat/lon` для API из `Address`, в `events` не дублируются.
  В `addresses` — компоненты `city` / `street` / `house`.
- Map: `importance` 1–2; `category`: `catastrophe` | `important`.
- Вес ленты: `0.5×relevance + 0.3×timeliness + 0.2×source_reliability`
  (`events.weight`); reliability — в `news_parser.sources.*.reliability`.
- Дедуп (KAN-19) — хук в `create_event`.

## WebApp (KAN-16)

- SvelteKit mini-app в `webapp/`: TikTok-лента nearby | city.
- Данные **только** с API (`GET /events/feed`) → БД.
- API base захардкожен: `/api` (Vite proxy → backend).
- User id: Max Bridge (`https://max.ru/js/max-web-app.js`) →
  `window.WebApp.initDataUnsafe.user.id` → заголовок `X-Max-User-Id`.
- Запросы к API: заголовок `ngrok-skip-browser-warning: true`.
- Dev-прокси: `/api` → `http://127.0.0.1:8000` (`webapp/vite.config.ts`,
  в Docker — `API_PROXY_TARGET`).
- UI: full-height snap-карточки, табы «Новости рядом / города», свайп вправо → город,
  картинка с lightbox, цветовая полоса по importance, SVG при `disaster_flag`,
  дата / источник (ссылка) / локация в одну строку; длинный body — синяя ссылка «ещё»,
  прокрутка текста только после раскрытия.

### Кнопка webapp в боте

- Приветствие (`bot_started` / `/start`) шлёт inline-кнопку типа **`open_app`**
  (`OpenAppButton`, текст «Открыть новости»).
- Мини-приложение привязывается к боту на платформе MAX
  ([docs/webapps](https://dev.max.ru/docs/webapps/introduction)): HTTPS URL webapp.
- Identity кнопки: `GET /me` → `web_app` (username) + `contact_id`.

### Ngrok (HTTPS для Max, без локальной установки)

- Секрет в корневом `.env`: **`NGROK=`** (authtoken). Не коммитить.
- Compose-сервис `ngrok` (`ngrok/ngrok`): `NGROK` → `NGROK_AUTHTOKEN`.
- Два флоу webapp — см. README «WebApp: два флоу» (Docker vs `npm run dev`).
- URL: `python scripts/ngrok_url.py` или http://localhost:4040  
  (если туннель выключен — публичная ссылка даёт 404).
- Upstream по умолчанию `webapp:5173`; для host Vite:
  `NGROK_UPSTREAM=host.docker.internal:5173`.
- Webapp proxy `/api` → `API_PROXY_TARGET` (host: `127.0.0.1:8000`,
  в compose webapp по умолчанию `host.docker.internal:8000`).
- Vite: `server.allowedHosts: true` (иначе Host от ngrok → 403).
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

# WebApp (KAN-16), в другом терминале — данные с API/БД:
# cd webapp && npm install && npm run dev
# → http://localhost:5173  (прокси /api → :8000)

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
