# parser_common (KAN-13)

Общий слой между **парсерами-источниками** и таблицей `events`.
Сам по себе ничего не тянет из сети и не пишет в БД без явного вызова handlers.

## Граница ответственности

| кто | делает |
|-----|--------|
| **KAN-11** (`parse_news`) | fetch RSS/HTML → `RawNewsArticle` → `ParserCandidate` → `persist_candidate` |
| **KAN-28** (`parse_mc`) | fetch УК/ЖЭК HTML → `RawMcNotice` → fan-out улиц → `ParserCandidate` |
| **KAN-10/12** (другие воркеры) | fetch источника → `ParserCandidate` → `persist_candidate` |
| **KAN-13** (этот пакет) | title/body, importance, disaster, **active_from/to (ML)**, place NER → addresses → `EventDraft` |
| **KAN-19** (`ml_dedup`) | NEW / DUPLICATE / UPDATE **внутри** `persist_candidate` |
| **KAN-14** (`events`) | хранение + read API ленты/карты |

## Контракт

```text
источник → ParserCandidate → normalize → EventDraft
                                      → ml_dedup.resolve → create|update|existing
```

- `active_from` / `active_to` — только ONNX (`ml/time/`), без keyword-rules.
- Место — spaCy NER → `StreetCatalog` / `GeoMatcher` → `addresses.id`.
- In-memory очередь: `parser_common.queue.CandidateQueue` (опционально).

Classify: `classify.py`. Time: `time_extract.py`. Place: `place_ner.py`.
Обучение: `ml/classify/`, `ml/time/`, `ml/dedup/`.
