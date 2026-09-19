# parse_mc (KAN-28)

Воркер сайтов управляющих компаний / ЖЭК Москвы:
`fetch → RawMcNotice → geo (все улицы) → ParserCandidate → persist_candidate → events`.

Общий scrape / geo-text / HTTP / seed — только из `parser_common`
(не импортировать `parse_news`).

## Источники

| key | Организация | listing |
|-----|-------------|---------|
| `pik_comfort` | ПИК-Комфорт | `pik-comfort.ru/news_all` |
| `granel` | ГранельЖКХ | `ggkm.ru/news/` |
| `zhil_nagatino` | ГБУ «Жилищник» Нагатино-Садовники | `gbuns.ru/organizacia/novosti` |
| `gbu_portal` | Портал новостей ГБУ «Жилищник» | `gbu-zhilishchnik.ru/novosti` |
| `moek` | ПАО «МОЭК» (теплосеть / отключения) | `moek.ru/press/news/` |

## Fan-out по улицам

Если в объявлении несколько улиц → **отдельное событие на каждую**.

`source_msg_id` = `{outlet}:{external_id}:addr:{address_id}` при multi-street;
при одной привязке — `{outlet}:{external_id}`.

`source` в events = `mc` (`EventSource.MC`).

## Snapshot событий

Общий для всех парсеров: `python -m parser_common.seed dump|load`
→ `src/parser_common/data/bootstrap_events.jsonl.gz` (все `source`, не только news).

## Запуск

```bash
set PYTHONPATH=src
alembic upgrade head
python -m main
```

Smoke:

```bash
set PYTHONPATH=src
python scripts/smoke_parser_collect.py --parser mc
```
