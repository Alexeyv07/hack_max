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
  max.py               # run_max_bot() — см. project/max.py
  main.py              # bot и/или API в одном процессе
tests/                 # pytest (API + handlers)
webapp/                # SvelteKit mini-app
AGENTS.md              # гайд для агентов
```

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

set PYTHONPATH=src
alembic upgrade head
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

```bash
copy .env.example .env          # указать MAX_BOT_TOKEN
docker compose up --build
```

Контейнер бота перед стартом сам делает `alembic upgrade head`.
В контейнере бота `DATABASE_HOST=postgres` задаётся через env и перекрывает `local.yaml`.

- Postgres: `localhost:5432`
- WebApp: http://localhost:5173
- Bot: контейнер `hack_max_bot`

## Миграции (Alembic)

```bash
set PYTHONPATH=src

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
