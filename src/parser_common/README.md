# parser_common (KAN-13)

Общий слой между **парсерами-источниками** и таблицей `events`.
Сам по себе ничего не тянет из сети и не пишет в БД без явного вызова handlers.

## Граница ответственности

| кто | делает |
|-----|--------|
| **KAN-11** (`parse_news`) | fetch RSS/HTML → `RawNewsArticle` → `ParserCandidate` → `persist_candidate` |
| **KAN-10/12** (другие воркеры) | fetch источника → `ParserCandidate` → `normalize` / `persist_candidate` → `create_event` |
| **KAN-13** (этот пакет) | title/body, importance, `disaster_flag`, optional geo → `EventDraft` / `EventCreate` |
| **KAN-19** (`ml_dedup`) | merge дублей **до** insert (хук в `create_event` или перед ним) |
| **KAN-14** (`events`) | хранение + read API ленты/карты |

KAN-11 (`src/parse_news/`) реализует новостной воркер; KAN-13 — общая **библиотека** normalize/classify между воркерами и `events`.

## Контракт для воркера парсера

```text
источник (чат / RSS / Max public)
        │
        ▼
  ParserCandidate          # только сбор полей, без classify
        │
        ▼
  normalize(...)           # title/body + importance + disaster + geo?
        │
        ▼
  EventDraft
        │
        ├─ (позже) ml_dedup / KAN-19
        ▼
  to_event_create(draft) → EventCreate
        │
        ▼
  events.handlers.create_event(session, ...)
```

Минимальный код воркера:

```python
from parser_common import ParserCandidate, normalize, to_event_create
from events.handlers.crud import create_event

candidate = ParserCandidate(
    raw_text=message_text,
    source="neighbors_chat",  # или news / max_public / …
    source_msg_id=str(msg_id),
    # title/body — если источник уже дал (новости); иначе None
    geo_text=None,  # опционально узкий кусок под гео
    address_id=None,  # если чат уже знает адрес — можно сразу
)

draft = normalize(candidate, geo_matcher=matcher, chat_coordinates=chat_xy)
event = create_event(session, to_event_create(draft))
```

Хелпер-обёртка: `persist_candidate(session, candidate, …)` — то же самое одной функцией
(см. `ingest.py`). Дедуп туда же подключится позже.

### Что парсер **не** делает

- не считает `importance` / `disaster_flag` сам (это classify);
- не пишет SQL напрямую в `events`;
- не дублирует title/body-эвристики и geo-алгоритм у себя.

### Что парсер **делает**

- поллинг / webhook / cron своего источника;
- фильтр явного мусора **алгоритмом** (KAN-10), без LLM;
- идемпотентность по `source` + `source_msg_id` (не плодить дубли до dedup);
- передаёт `GeoMatcher` снимок территории чата (KAN-6 / chat_link), если нужен geo.

## API пакета

- `ParserCandidate` — вход
- `EventDraft` — выход normalize
- `normalize(candidate, *, geo_matcher=None, chat_coordinates=None)`
- `to_event_create(draft)`
- `persist_candidate(session, candidate, …)` — normalize + create_event

Classify: `classify.py` (ONNX → rules). Обучение: `ml/classify/`.
Ручной прогон: `scripts/classify_try.py`.
