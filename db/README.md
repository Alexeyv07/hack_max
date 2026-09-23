# Миграции БД (вместо Alembic)

Порядок: `NNNN_name.up.sql` / `NNNN_name.down.sql` в `db/migrations/`.
Учёт: таблица `schema_migrations`.

## Команды

```bash
# статус / накатить / откатить
PYTHONPATH=src python scripts/migrate.py status
PYTHONPATH=src python scripts/migrate.py up
PYTHONPATH=src python scripts/migrate.py down
PYTHONPATH=src python scripts/migrate.py down --steps 3

# пометить все версии applied без выполнения SQL (редкий repair)
PYTHONPATH=src python scripts/migrate.py stamp
```

## Docker

Образ `docker/postgres/Dockerfile` на **первом** `initdb`:

1. `00_migrate.sh` — все `*.up.sql`
2. `01_load_seed.sh` — `COPY` из `docker/postgres/seed/*.csv.gz`

Повторный старт с существующим volume миграции не гоняет.
Пересоздать данные: `docker compose down -v && docker compose up -d --build postgres`.

## Новая миграция

1. Добавить пару файлов `0014_....up.sql` + `0014_....down.sql`
2. Локально: `python scripts/migrate.py up`
3. В Docker на уже живом volume: тот же `migrate.py up` (или пересоздать volume)

Seed CSV пересобрать из jsonl: `PYTHONPATH=src python scripts/build_pg_seed_dumps.py`
