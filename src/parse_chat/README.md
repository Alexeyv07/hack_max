# parse_chat (KAN-10)

Бот слушает `message_created` во **всех подключённых** домовых чатах
(`chats.chat_type='chat'`) и отдаёт сырьё в общий пайплайн:

```
Max message_created
  → минимальный filter (бот / команда / пусто / стикер / флуд)
  → ParserCandidate(+ image_url) без address_id
  → normalize: place NER → иначе geo чата; classify/time
  → ml_dedup → events
```

## Фильтр (permissive)

Allowlist **нет**. Важность и «бытовуха» — у **classify ML** (`importance=3` не в ленту).

Drop только:
- сообщения от ботов, `/команды`
- пусто без фото
- только стикер/файл без текста и без image
- целиком короткое приветствие («привет», «ок»)
- флуд: тот же текст от user слишком часто

Мнения, обсуждения, новости без ключевых слов — **проходят**.

## Картинки

Из `body.attachments` (`type=image|photo`) → `payload.url`.

Если пришло **только фото** (без текста) — не создаём событие сразу:
ждём следующее сообщение **того же автора** в чате (окно
`photo_attach_window_seconds`, дефолт 10 мин) и вешаем фото на него.

Текст **без** фото не дропается. Фото+подпись в одном сообщении — сразу.

Стикеры не считаются фото.

## Latency (для демо)

Сообщение из чата **не ждёт** news/mc и не блокирует Max polling:

1. Handler сразу возвращается (`create_task` + dedicated thread pool)
2. Полный ML: spaCy geo → fallback чат; time-ONNX; classify; dedup
3. `updates_limit: 50` — быстрее слив get_updates
4. При старте бота прогреваются classify + time + dedup

Для показа судьям можно временно выключить тяжёлые парсеры:
`runtime.enable_news_parser: false`, `enable_mc_parser: false`.
