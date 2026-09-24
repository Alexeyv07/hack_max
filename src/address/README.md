# Локальный геопоиск

`GeoMatcher` — общий хелпер для парсеров и `parser_common`.
Он работает с адресами из нашей БД, без сетевых запросов и LLM.

## Контракт территории

`addresses` хранит структурированные `city`, `district`, `street`, `house` вместе с
`address_text`, индексом и координатами. Для Москвы канонический `district` определяется по
координатам дома и OSM-границам `boundary=administrative + admin_level=8`. Locality из адресных
тегов/старого `address_text` остаётся только fallback и проходит очистку служебных значений.

Для geo parser-ов вызывающий модуль по-прежнему передаёт **явно выбранные ключи адресов
территории чата** в `load_addresses` либо уже отобранные объекты `Address` в `GeoMatcher`.
`GeoMatcher` не определяет территорию по свободному тексту и не расширяет пустой набор до всей БД.

```python
from address.db.queries import load_addresses
from address.geocoding import GeoMatcher
from project.database import session_scope

# chat_area_address_keys и chat_coordinates предоставляет модуль чатов.
with session_scope() as session:
    addresses = load_addresses(session, address_texts=chat_area_address_keys)

matcher = GeoMatcher(addresses)  # создать один раз для территории
geo = matcher.resolve(message_text, chat_coordinates=chat_coordinates)
# Для Event используйте geo.address_id: координаты в events больше не копируются.
```

Снимок нужно пересоздать после обновления справочника или территории чата.
Вызов из воркера парсера / `parser_common.normalize(..., geo_matcher=...)`.
Не копируйте алгоритм в каждый парсер.


## Общий in-memory `StreetCatalog`

`StreetCatalog` — существующий snapshot адресного справочника. Parser-модули используют его
для stemming/fuzzy поиска улиц. KAN-7 переиспользует тот же класс с `city=None`: каталог также
держит публичные дома (`address_id`, city/district/street/house, postal, lat/lon), умеет строить
иерархию кнопок, fuzzy-поиск полного адреса и nearest lookup для карты.

В `chat_link` экземпляр кэшируется process-wide после одного `SELECT addresses`; SQL на каждый
callback или движение карты не выполняется. После обновления/seed справочника snapshot нужно
явно пересоздать (`get_address_catalog(refresh=True)`) либо перезапустить процесс.

### Районы Москвы

Готовый historical snapshot адресов не содержал полного набора муниципальных районов: locality
OSM у многих домов отсутствует или содержит не район (`Moscow`, ЖК, СНТ и т. п.). Поэтому для
первого picker районов используется отдельный **offline snapshot границ OSM admin_level=8**.
Runtime бота по сети за районами не ходит.

Скачать снимок границ и один раз заполнить существующую БД:

```bash
curl --fail --show-error --max-time 210 \
  --data-urlencode 'data@src/address/data/moscow_districts.overpassql' \
  https://maps.mail.ru/osm/tools/overpass/api/interpreter \
  -o /tmp/moscow-districts.json
PYTHONPATH=src python -m address.backfill_districts /tmp/moscow-districts.json
```

После backfill перезапустите бот, чтобы process-wide `StreetCatalog` перечитал snapshot:

```bash
docker compose restart bot
```

При полной переподготовке справочника тот же snapshot можно передать сразу в pipeline:

```bash
PYTHONPATH=src python -m address.prepare_osm /tmp/moscow-osm.json \
  --output /tmp/moscow-prepared \
  --district-boundaries /tmp/moscow-districts.json
```

`address_text` при этом не меняется: это сохраняет существующий natural key/id домов. Повторный
seed не стирает уже определённый район, если входной файл района не содержит.

## Порядок поиска

1. Нормализация регистра, `ё → е`, сокращений (`ул.`, `пр-т`, `д.`, `к`, `стр.`).
2. Изолированные шесть цифр — точный поиск по индексу в загруженном снимке.
   Индекс не уникален: если домов несколько, уточняем по улице и номеру.
   Неизвестный индекс не заменяем поиском по другим индексам.
3. Без индекса — сравнение улиц через RapidFuzz в пределах переданного набора.
   Порог по умолчанию 90/100, отрыв от второго кандидата — минимум 5 баллов.
   Явно указанные номер, корпус и строение сравниваем точно.
4. Неоднозначный, слабый или отсутствующий результат — координаты чата
   (`scope="chat"`), а без них — `latitude=None`, `longitude=None`, `scope="city"`.

Результат содержит `scope`, `method`, `score`, координаты, найденный `address_text` и `address_id`.
`score` — сходство строк, не вероятность правильного адреса. Без номера дома
несколько записей одной улицы считаются неоднозначным результатом.
Начальная версия поддерживает именительный падеж названий и явный номер
`д. / дом`; это не полный морфологический разбор русского текста.
Нормализованные строки кэшируются в памяти; отдельного столбца пока не требуется.

## Первичный ключ и связь с событиями

После объединения с KAN-14 `addresses.id` — короткий стабильный PK, а
`address_text` остаётся `UNIQUE` и используется для идемпотентного seed/upsert.
`events.address_id` ссылается на `addresses.id`; координаты события не дублируются
в таблице `events`, а читаются из связанного `Address`. Миграции `0004`/`0005`
переводят схему на FK `events.address_id → addresses`.

```bash
python -m pip install -e '.[dev]'
PYTHONPATH=src python scripts/migrate.py up
python -m unittest discover -s tests -p test_address_geocoding.py -v
```

Тесты схемы дополнительно требуют PostgreSQL с правом `CREATE SCHEMA` и
переменную `ADDRESS_TEST_DATABASE_URL`. Они работают в отдельных схемах
и откатывают изменения. Миграции создают структуру. При запуске полного стека
в Docker seed `addresses`/`events` грузит init образа Postgres
(`docker/postgres` → `COPY` из CSV).


## Загрузка адресов

При обычном запуске полного стека отдельная команда не нужна:

```bash
docker compose up --build
```

На первом initdb Postgres накатывает `db/migrations` и `COPY` seed CSV.
Повторный старт с тем же volume seed не перезатирает.

Локальный файл JSONL (один объект на строку), также поддерживается `.jsonl.gz`:

```json
{"address_text":"Москва, улица Примерная, д. 1","postal_code":null,"latitude":55.75,"longitude":37.6,"is_private":null}
```

Это пример формата, не проверенный реальный адрес. Поля `id` и метаданные
источника в файл загрузки можно не включать; `id` генерирует БД.

Для ручной проверки или загрузки после `pip install -e ".[dev]"`:

```bash
python -m address.seed /путь/к/адресам.jsonl.gz --validate-only
python -m address.seed /путь/к/адресам.jsonl.gz
```

Сначала проверяется весь файл. Повторная загрузка обновляет запись по
`address_text`, сохраняя её `id`. Пустые индекс и тип дома не затирают уже
известные значения. Весь импорт выполняется в одной транзакции.
Одинаковые строки объединяются; разные координаты или другие данные для
одного `address_text` вызывают ошибку до записи в БД. Переименование адресов
этот загрузчик не выполняет.

Готовая московская выгрузка находится в `src/address/data/moscow.jsonl.gz`:
125 562 адреса, из них 101 611 с индексом. Конфликтующие дубли вынесены отдельно,
часть пропущенных индексов дополнена из локального ГАР.
Команды загрузки, источники и ограничения — в [описании данных](data/README.md).
Загрузчик и работающий бот не обращаются к внешним геокодерам.
