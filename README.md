# Проект «Умный город» — бот и WebApp для мессенджера Max

## Структура

```
conf/                  # local.yaml / prod.yaml
src/
  project/             # общее: config, logging, database
  auth/                # модуль авторизации пользователей
    models/            # доменные модели
    db/                # SQLAlchemy ORM
    handlers/          # бизнес-логика + запросы
    commands/          # привязка к Max-событиям (/start, bot_started)
  main.py              # точка входа бота
webapp/                # SvelteKit mini-app
```

## Режимы запуска

### A. Локально: bot + webapp на хосте, Postgres в Docker

```bash
docker compose up -d postgres

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -e ".[dev]"
copy .env.example .env          # указать MAX_BOT_TOKEN

set PYTHONPATH=src
python -m main

# в другом терминале
cd webapp && npm install && npm run dev
```

`conf/local.yaml` смотрит на `localhost:5432` — это порт Postgres из Docker.

### B. Всё в Docker

```bash
copy .env.example .env          # указать MAX_BOT_TOKEN
docker compose up --build
```

В контейнере бота `DATABASE_HOST=postgres` задаётся через env и перекрывает `local.yaml`.

- Postgres: `localhost:5432`
- WebApp: http://localhost:5173
- Bot: контейнер `hack_max_bot`

## Конфиг

- `APP_ENVIRONMENT=local|prod` выбирает `conf/local.yaml` или `conf/prod.yaml`
- `local.yaml` — под локальный bot/webapp + Postgres в Docker (`localhost`)
- `prod.yaml` — без секретов; пароль БД, токен бота и т.п. только через env
- `.env` / `.env.example` — только чувствительные секреты (например `MAX_BOT_TOKEN`)
- Env перекрывает YAML (`DATABASE_PASSWORD`, `MAX_BOT_TOKEN`, `DATABASE_HOST`, …)

## Авторизация

При `bot_started` и `/start` пользователь upsert’ится в таблицу `users`.

## Линтеры

```bash
ruff format src
ruff check src
```

GitHub Actions на каждый push проверяет `ruff format --check`, `ruff check` и `npm run check` для webapp.

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
