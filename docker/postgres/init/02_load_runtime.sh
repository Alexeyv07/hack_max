#!/bin/sh
# Initdb: runtime-дамп (users/chats/…) после addresses+events.
# Файлы: /seed/runtime/*.csv.gz (scripts/dump_db.py dump).
# addresses/events сюда НЕ входят — их грузит 01_load_seed.sh.
set -eu

RUNTIME_DIR="${RUNTIME_SEED_DIR:-/seed/runtime}"

if [ ! -d "$RUNTIME_DIR" ]; then
  echo "runtime seed: нет каталога $RUNTIME_DIR — skip"
  exit 0
fi

has_csv=0
for f in "$RUNTIME_DIR"/*.csv.gz; do
  if [ -f "$f" ]; then
    has_csv=1
    break
  fi
done
if [ "$has_csv" -eq 0 ]; then
  echo "runtime seed: нет *.csv.gz — skip"
  exit 0
fi

table_has_rows() {
  table="$1"
  n=$(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -Atc \
    "SELECT CASE WHEN EXISTS (SELECT 1 FROM ${table} LIMIT 1) THEN 1 ELSE 0 END")
  [ "$n" = "1" ]
}

load_one() {
  table="$1"
  gz="$2"

  if [ ! -f "$gz" ]; then
    echo "WARN: $gz missing — skip ${table}"
    return 0
  fi
  if table_has_rows "$table"; then
    echo "${table}: already has rows — skip"
    return 0
  fi

  header=$(gunzip -c "$gz" | head -n 1 | tr -d '\r')
  echo "Loading ${table} from ${gz} ..."
  gunzip -c "$gz" > "/tmp/${table}.csv"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c \
    "COPY ${table} (${header}) FROM '/tmp/${table}.csv' WITH (FORMAT csv, HEADER true, NULL '\\N');"
  seq=$(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -Atc \
    "SELECT COALESCE(pg_get_serial_sequence('${table}', 'id'), '')")
  if [ -n "$seq" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c \
      "SELECT setval('${seq}', COALESCE((SELECT MAX(id) FROM ${table}), 1));"
  fi
  rm -f "/tmp/${table}.csv"
  echo "${table}: done"
}

LOADED=""

mark_loaded() {
  LOADED="${LOADED} $1 "
}

was_loaded() {
  case "$LOADED" in
    *" $1 "*) return 0 ;;
    *) return 1 ;;
  esac
}

# FK-safe порядок (как scripts/dump_db.py LOAD_ORDER)
for table in \
  users \
  chats \
  users_chat \
  chat_addresses \
  user_chat_addresses \
  chat_links \
  bot_group_registry \
  news_parser_cursors \
  mc_parser_cursors \
  notify_cursors \
  notify_digests \
  notify_chat_messages \
  notify_deliveries
do
  gz="${RUNTIME_DIR}/${table}.csv.gz"
  if [ -f "$gz" ]; then
    load_one "$table" "$gz"
  fi
  mark_loaded "$table"
done

# Доп. таблицы (кроме addresses/events и уже обработанных)
for gz in "$RUNTIME_DIR"/*.csv.gz; do
  [ -f "$gz" ] || continue
  base=$(basename "$gz" .csv.gz)
  if [ "$base" = "addresses" ] || [ "$base" = "events" ]; then
    continue
  fi
  if was_loaded "$base"; then
    continue
  fi
  load_one "$base" "$gz"
done

echo "runtime seed: ok"
