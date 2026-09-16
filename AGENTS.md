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

- `ParserCandidate` → `normalize()` → `EventDraft` → `to_event_create` → events.
- Title/body: эвристика (`text.py`), **не** LLM.
- **Importance classify** — каскад (см. `src/parser_common/classify.py`, `ml/classify/MODEL.md`):
  1. ONNX `rubert-tiny2` (если есть артефакт + deps)
  2. keyword rules (+ `ml/classify/rules.yaml`)
  - `importance` и `disaster_flag` независимы: ML → только importance; флаг ЧС → keywords.
- Geo: опциональный `address.geocoding.GeoMatcher`.
- Дедуп **не здесь** — KAN-19.
- Обучение только в `ml/classify/train_torch.py` (GPU). Не импортировать `ml/` из `src`.
- Синтетика: `bootstrap_data.py` → `data/bootstrap.jsonl` (не перезаписывает `train.jsonl`; append — флаг `--merge-into-train`).
- Ручной прогон: `python scripts/classify_try.py` (`PYTHONPATH=src`).

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e ".[ml]"
python ml/classify/bootstrap_data.py
python ml/classify/train_torch.py --config ml/classify/config_torch.yaml
```

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
- Гео события хранится через `events.address_id -> addresses.id`; `lat/lon` для API вычисляются из `Address`, в `events` не дублируются.
- City feed: `importance=1` только с `disaster_flag=true`.
- Map: `importance` 1–2; `category`: `catastrophe` | `important`.
- Вес: `events.weight.compute_weight`. Дедуп (KAN-19) — хук в `create_event`.

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
# ручной прогон: set PYTHONPATH=src & python scripts/classify_try.py

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
