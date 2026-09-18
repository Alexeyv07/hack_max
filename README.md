# Проект «Умный город» — бот и WebApp для мессенджера Max

## Contributing flow

1. Создать ветку от main: `git checkout -b your-feature-name`
2. Коммиты с описанием: `git commit -m "описание изменений"`
3. Push: `git push origin your-feature-name`
4. Создать pull request в main и смержить
5. Переключиться на main: `git checkout main`
6. Обновить local main: `git pull origin main`

Важные моменты:
- Если меняете файл, который параллельно трогает кто-то ещё — предупредите и мержите быстрее
- Конфликты решаем в локальной ветке
- Директивы коммитов: `FEAT:`, `FIX:`, `REFACTOR:`, `DOCS:`, `TEST:`

## Структура

```
conf/                  # local.yaml / prod.yaml
alembic/               # миграции БД
src/
  project/             # общее: config, logging, database
  auth/                # модуль авторизации пользователей
    models/            # доменные модели
    db/                # SQLAlchemy ORM
    handlers/          # бизнес-логика + запросы
    commands/          # привязка к Max-событиям (/start, bot_started)
  events/              # события (лента nearby/city)
    models/
    db/
    handlers/          # CRUD + правила ленты
    api/               # FastAPI routes → handlers
    weight.py          # чистый расчёт веса
  chats/               # членство в чатах (пока mock handlers)
  parse_news/          # KAN-11: новостной воркер (RSS/HTML → events)
  parser_common/       # KAN-13: Candidate→Draft→EventCreate (+ ingest)
  user_chat/           # KAN-5: хранение чатов, address_id и User <-> Chat
  chat_link/           # KAN-7: заготовка onboarding-flow подключения чата
  parser_common/       # KAN-13: Candidate→Draft→EventCreate (+ ingest); парсеры-воркеры — отдельно
  max.py               # run_max_bot() — см. project/max.py
  main.py              # bot и/или API в одном процессе
tests/                 # pytest (API + handlers)
ml/                    # обучение classify (KAN-13) и dedup (KAN-19); НЕ src
scripts/               # утилиты (entrypoint, classify_try, smoke_news_collect)

webapp/                # SvelteKit mini-app
AGENTS.md              # гайд для агентов
```

## Скрипты (`scripts/`)

| скрипт | зачем |
|--------|--------|
| `bot_entrypoint.py` | контейнер бота: `alembic upgrade head`, затем `python -m main` |
| `classify_try.py` | REPL для importance-классификатора (ONNX → rules) |
| `smoke_news_collect.py` | live smoke KAN-11: 1 страница collect по enabled outlet |

### `classify_try.py`

Нужны артефакты после `train_torch.py` и deps `pip install -e ".[ml]"`.

```bash
set PYTHONPATH=src
python scripts/classify_try.py
```

Ввод — одна строка текста (заголовок/пост). Пустая строка / `q` — выход.
Многострочный режим: `:m`, конец блока — строка с одной точкой `.`

На каждый запрос печатает raw ONNX (`p1/p2/p3`), ответ rules и итоговый каскад
(`importance`, `disaster_flag`, `method`).

### `smoke_news_collect.py`

Live-проверка адаптеров KAN-11 (сеть, без записи в БД): incremental, 1 страница.

```bash
set PYTHONPATH=src
python scripts/smoke_news_collect.py
python scripts/smoke_news_collect.py --outlet m24
```

### `bot_entrypoint.py`

Точка входа Docker-образа бота (см. compose). Локально обычно не нужен —
достаточно `alembic upgrade head` и `python -m main`.

## Режимы запуска

### A. Локально: bot + webapp на хосте, Postgres в Docker

```bash
docker compose up -d postgres

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -e ".[dev]"
pre-commit install
copy .env.example .env          # указать MAX_BOT_TOKEN

alembic upgrade head
python -m address.seed src/address/data/moscow.jsonl.gz
python -m main

# HTTP API: http://localhost:8000/docs  (если runtime.enable_api=true)
# Отключить бот или API: conf/local.yaml → runtime.enable_bot / enable_api

# в другом терминале
cd webapp && npm install && npm run dev
```

Тесты:

```bash
pip install -e ".[dev]"
pytest
```

`conf/local.yaml` смотрит на `localhost:5432` — это порт Postgres из Docker.

### B. Всё в Docker

Перед сборкой нужны веса classify (ONNX ~110MB, в git не лежат):

```bash
# один раз на машине с GPU:
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e ".[ml]"
python ml/classify/train_torch.py --config ml/classify/config_torch.yaml
# → ml/classify/artifacts/importance_model.onnx (+ tokenizer, meta)
```

```bash
copy .env.example .env          # указать MAX_BOT_TOKEN
docker compose up --build
```

Контейнер бота:
- ставит `.[ml-runtime]` (onnxruntime + transformers, без torch);
- копирует `ml/classify/artifacts` в образ и монтирует тот же каталог с хоста (`:ro`) —
  после переобучения достаточно `docker compose restart bot`;
- перед стартом проверяет наличие ONNX и делает `alembic upgrade head`;
- если таблица `addresses` пустая, автоматически загружает московский справочник из
  `src/address/data/moscow.jsonl.gz`; при следующих запусках повторный импорт не выполняется.

`DATABASE_HOST=postgres` в compose перекрывает `local.yaml`.

- Postgres: `localhost:5432`
- WebApp: http://localhost:5173
- Bot: контейнер `hack_max_bot`

## Миграции (Alembic)

Чаты соседей (KAN-5): [модели, handlers и пример вызова](src/user_chat/README.md).
После `/start` пользователь зарегистрирован, но его нужно отдельно связать с чатом:
лента и карта используют только реальные записи `users_chat`.

```bash
# применить все миграции
alembic upgrade head

# откатить на одну ревизию назад
alembic downgrade -1

# откатить до конкретной ревизии
alembic downgrade 0001_create_users

# создать новую миграцию после изменения ORM-моделей
alembic revision --autogenerate -m "описание изменений"

# текущее состояние
alembic current
alembic history
```

## Конфиг

- `APP_ENVIRONMENT=local|prod` выбирает `conf/local.yaml` или `conf/prod.yaml`
- `local.yaml` — под локальный bot/webapp + Postgres в Docker (`localhost`)
- `prod.yaml` — без секретов; пароль БД, токен бота и т.п. только через env
- `.env` / `.env.example` — только чувствительные секреты (например `MAX_BOT_TOKEN`)
- Env перекрывает YAML (`DATABASE_PASSWORD`, `MAX_BOT_TOKEN`, `DATABASE_HOST`, …)

## Линтеры и pre-commit

```bash
pip install -e ".[dev]"
pre-commit install
ruff format src
ruff check src
```

Перед коммитом pre-commit прогоняет `ruff` + `ruff format`. CI — то же плюс `npm run check` для webapp.
