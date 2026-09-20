# Проект «Умный город» — бот и WebApp для мессенджера Max

Лента событий рядом / по городу: парсеры СМИ и УК → normalize + ML → dedup → `events` → WebApp.

Гайд для агентов: [`AGENTS.md`](./AGENTS.md). Пайплайн (mermaid): [`docs/pipeline_parser_to_feed.md`](./docs/pipeline_parser_to_feed.md).

## Contributing flow

1. Ветка от `main`: `git checkout -b your-feature-name`
2. Коммиты: `FEAT:` / `FIX:` / `REFACTOR:` / `DOCS:` / `TEST:` + краткое описание на русском
3. `git push origin your-feature-name` → PR в `main`
4. После merge: `git checkout main && git pull origin main`

## Структура

```
conf/                  # local.yaml / prod.yaml (+ ml_dedup, ml_enrich)
alembic/               # миграции (в т.ч. active_from/to)
src/
  project/             # config, logging, database
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

### Поток данных (кратко)

```
parse_* → ParserCandidate
       → normalize (title/body, importance, disaster, active_*, geo)
       → ml_dedup (NEW / DUP / UPDATE, окно 21 день)
       → events → GET /events/feed
```

Geo: воркер (regex + spaCy LOC → StreetCatalog) → при `address_id=null` ещё `place_ner` в normalize.  
Time: только ML (`ml/time`); без ONNX поля `null`. Classify: ONNX → rules (переобучать не обязательно).

## Скрипты (`scripts/`)

| скрипт | зачем |
|--------|--------|
| `bot_entrypoint.py` | Docker bot: проверка ML-артефактов, `alembic upgrade`, seed, `main` |
| `classify_try.py` | REPL importance (ONNX → rules) |
| `smoke_parser_collect.py` | live smoke news/mc collect |
| `ngrok_url.py` | публичный HTTPS URL туннеля |

```bash
set PYTHONPATH=src
python scripts/classify_try.py
python scripts/smoke_parser_collect.py --parser news --outlet m24
python -m parser_common.seed dump
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

Артефакты → `ml/*/artifacts/` (в git не коммитим тяжёлые `.onnx`; монтируются в Docker).

## Режимы запуска

Нужен `.env` из `.env.example` (`MAX_BOT_TOKEN`, для Max — `NGROK`).

### Postgres

```bash
docker compose up -d postgres
```

`conf/local.yaml` → `localhost:5432`.

### Подключение домового чата (KAN-7)

`chat_link` реализует один onboarding-screen и 4 способа выбора дома: bot-picker
`город → район → улица → дом`, индекс, карта WebApp и текстовый WebApp-поиск.
Адресные списки строятся из in-memory `StreetCatalog`; реальные MAX group `chat_id` и membership
сохраняются через `user_chat`. Если чат создаётся впервые, администратор добавляет бота в группу,
назначает его администратором с правом `read_all_messages`, после чего связь подтверждается MAX API
и завершается автоматически. Подробнее: `src/chat_link/README.md`.

### WebApp: два флоу

Публичный HTTPS — сервис **ngrok** в Compose (`NGROK=` в `.env`).

```bash
python scripts/ngrok_url.py   # или http://localhost:4040
```

URL вида `https://….ngrok-free.dev` вставляется в настройки бота на платформе MAX.  
После каждого нового туннеля сверяйте URL через `python scripts/ngrok_url.py`: если в MAX остался старый endpoint, mini-app покажет `ERR_NGROK_3200 ... is offline`. В этом случае поднимите `webapp ngrok` и обновите URL mini-app в настройках MAX.

#### Флоу 1 — webapp в Docker

```bash
pip install -e ".[dev]"
alembic upgrade head
python -m main                    # :8000

docker compose up -d webapp ngrok # :5173 + публичный URL
```

#### Флоу 2 — webapp на хосте

```bash
python -m main
cd webapp && npm install && npm run dev   # :5173, proxy /api → :8000

# опционально туннель:
# $env:NGROK_UPSTREAM="host.docker.internal:5173"; docker compose up -d ngrok
```

### A. Локально bot + API

```bash
docker compose up -d postgres
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pip install -e ".[ml-runtime]"   # onnxruntime, transformers, spacy
python -m spacy download ru_core_news_md
pre-commit install
copy .env.example .env

alembic upgrade head
python -m address.seed src/address/data/moscow.jsonl.gz
python -m main
# API: http://localhost:8000/docs
```

```bash
pytest
```

### B. Всё в Docker

Перед сборкой желательны веса classify (и после разметки — time):

```bash
# GPU-машина:
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -e ".[ml]"
python ml/classify/train_torch.py --config ml/classify/config_torch.yaml
# → ml/classify/artifacts/importance_model.onnx
# опционально time/dedup — см. ml/TRAIN.md
```

```bash
copy .env.example .env
docker compose up --build
```

Контейнер `bot`:
- `pip install .[ml-runtime]` + `spacy download ru_core_news_md`;
- COPY/mount: `ml/classify|time|dedup/artifacts`;
- без ONNX — soft WARN и fallback (rules / null dates / hash embed);
- `alembic upgrade head`, seed addresses/events при пустых таблицах.

- Postgres: `localhost:5432`
- WebApp: http://localhost:5173
- API/bot: http://localhost:8000

## Миграции (Alembic)

```bash
alembic upgrade head
alembic current
alembic history
```

Актуальный head: `0013_events_active_window` (`active_from` / `active_to`).
Перед ним: `0011_chat_link` (district + chat_links), `0012_chat_group_type`.

## Конфиг

- `APP_ENVIRONMENT=local|prod` → `conf/local.yaml` | `prod.yaml`
- `ml_dedup.active_days: 21`, пороги cosine, `ml_enrich.spacy_model`
- Env перекрывает YAML (`DATABASE_*`, `MAX_BOT_TOKEN`, `ML_DEDUP_ENABLED`, …)
- Секреты только в `.env`

## Линтеры

```bash
pip install -e ".[dev]"
pre-commit install
ruff format src tests
ruff check src tests
```
