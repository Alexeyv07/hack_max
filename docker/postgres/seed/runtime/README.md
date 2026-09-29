# Runtime seed (users, chats, memberships, user_chat_addresses, bot_group_registry, notify, cursors, …)

Собрать с живой БД (без addresses/events — они в `../addresses.csv.gz` и `../events.csv.gz`):

```bash
set PYTHONPATH=src
python scripts/dump_db.py dump
# → docker/postgres/seed/runtime/*.csv.gz + manifest.json
```

Загрузить в уже поднятую БД:

```bash
python scripts/dump_db.py load
# или с перезаписью: python scripts/dump_db.py load --force
```

На **первом** `initdb` Postgres образ сам подхватывает этот каталог
(`docker/postgres/init/02_load_runtime.sh`) после миграций и seed addresses/events.

`address_id` / `event_id` в runtime-дампе должны совпадать с id из seed адресов и событий.

После миграций, добавивших колонки с `DEFAULT` (например `user_chat_addresses.added_at`),
старый csv без этих полей всё ещё грузится: `COPY` перечисляет только колонки из header/manifest,
а Postgres подставляет default. Новый dump уже содержит полный набор колонок.
