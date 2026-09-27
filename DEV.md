# Проект «Умный город» — бот и WebApp для мессенджера Max

## Contributing flow

1. Ветка от `main`: `git checkout -b your-feature-name`
2. Коммиты: `FEAT:` / `FIX:` / `REFACTOR:` / `DOCS:` / `TEST:` + краткое описание на русском
3. `git push origin your-feature-name` → PR в `main`
4. После merge: `git checkout main && git pull origin main`

## Структура

```
conf/                  # local.yaml / prod.yaml (+ ml_dedup, ml_enrich)
db/migrations/         # SQL up/down (вместо Alembic)
docker/postgres/       # образ Postgres: migrate + COPY seed
DEPLOY.md              # prod GHCR + ONNX Release `models` + docker-compose.prod.yaml
src/
  project/             # config, logging, database, sql_migrate
  auth/                # пользователи Max
  address/             # addresses + StreetCatalog + GeoMatcher (+ district)
  events/              # CRUD + feed/map API (KAN-14)
  user_chat/           # чаты соседей (KAN-5)
  chat_link/           # onboarding чата (KAN-7)
  parse_news/          # KAN-11: RSS/HTML СМИ → Candidate
  parse_mc/            # KAN-28: сайты УК/ЖЭК → Candidate
  parser_common/       # KAN-13: normalize (classify, time, place) + ingest
  ml_dedup/            # KAN-19: NEW | DUPLICATE | UPDATE
  max.py / main.py     # bot + API + парсеры в одном процессе
ml/                    # обучение (НЕ импортируется из src)
  classify/            # importance 1|2|3 → ONNX
  time/                # active_from / active_to → ONNX
  dedup/               # embeddings + пороги cosine
  TRAIN.md             # команды обучения после разметки
webapp/                # SvelteKit mini-app
docs/                  # схемы пайплайна
tests/ scripts/
```

## Скрипты (`scripts/`)

| скрипт                    | зачем                                                               |
|---------------------------|---------------------------------------------------------------------|
| `bot_entrypoint.py`       | Docker bot: ML-check → `main` (схема/seed — в образе Postgres) |
| `migrate.py`              | `up` / `down` / `status` / `stamp` для `db/migrations` |
| `build_pg_seed_dumps.py`  | jsonl → `docker/postgres/seed/{addresses,events}.csv.gz` |
| `dump_db.py`              | dump/load runtime-таблиц (users/chats/…; без addresses/events) |
| `classify_try.py`         | REPL importance (ONNX → rules)                                      |
| `smoke_parser_collect.py` | live smoke news/mc collect                                          |

```bash
set PYTHONPATH=src
python scripts/classify_try.py
python scripts/smoke_parser_collect.py --parser news --outlet m24
python -m parser_common.seed dump

# демо-БД для судей: addresses/events — seed; остальное — runtime dump
python scripts/build_pg_seed_dumps.py
python scripts/dump_db.py dump          # → docker/postgres/seed/runtime/
python scripts/dump_db.py load          # в уже мигрированную БД
```

## ML: обучение

Подробно: [`ml/TRAIN.md`](./ml/TRAIN.md).

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e ".[ml]"
python -m spacy download ru_core_news_md

# importance (опционально — артефакты уже могут быть)
python ml/classify/train_torch.py --config ml/classify/config_torch.yaml

# active_from / active_to (нужна разметка ml/time/data/train.jsonl)
python ml/time/bootstrap_data.py
python ml/time/train_torch.py --config ml/time/config_torch.yaml

# пороги dedup (пары ml/dedup/data/pairs.jsonl)
python ml/dedup/bootstrap_pairs.py
python ml/dedup/eval_threshold.py --config ml/dedup/config.yaml
```

Артефакты → `ml/*/artifacts/` (в git не коммитим тяжёлые `.onnx`; в local compose
монтируются, в prod — внутри bot-образа из GitHub Release `models`, см. `DEPLOY.md`).

## Запуск

Нужен `.env` из `.env.example` (`MAX_BOT_TOKEN`, `CLOUDPUB_TOKEN`, `AITUNNEL_API_KEY`).

```bash
# Dev — всё в Docker (postgres + bot + webapp + cloudpub):
docker compose up -d --build
docker compose logs -f cloudpub   # https://….cloudpub.ru → в Max

# Бот на хосте — не поднимайте сервис bot:
docker compose up -d postgres webapp cloudpub
python -m main

# Prod — публичные образы GHCR (тег v* → Actions), ONNX внутри bot:
# см. DEPLOY.md (куда залить ONNX в Release `models`)
# docker compose -f docker-compose.prod.yaml --env-file .env up -d
```

## Миграции (SQL)

См. [`db/README.md`](./db/README.md).

```bash
set PYTHONPATH=src
python scripts/migrate.py status
python scripts/migrate.py up
python scripts/migrate.py down          # на 1 шаг
python scripts/migrate.py down --steps 3
```

## Конфиг

- `APP_ENVIRONMENT=local|prod` → `conf/local.yaml` | `prod.yaml`
- `ml_dedup.active_days: 21`, пороги cosine, `ml_enrich.spacy_model`
- Env перекрывает YAML (`DATABASE_*`, `MAX_BOT_TOKEN`, `ML_DEDUP_ENABLED`, …)
- Секреты только в `.env`: `MAX_BOT_TOKEN`, `CLOUDPUB_TOKEN`, `AITUNNEL_API_KEY`

## Линтеры

```bash
pip install -e ".[dev]"
pre-commit install
ruff format src tests
ruff check src tests
```
