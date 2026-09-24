#!/bin/bash
# Загрузка addresses + events через psql \copy (после alembic).
# Идемпотентно: пропускает таблицу, если в ней уже есть строки.
# Нужны: psql, gzip; DATABASE_* или PG* env.
set -euo pipefail

SEED_DIR="${SEED_DIR:-/app/docker/postgres/seed}"
ADDR_GZ="${SEED_DIR}/addresses.csv.gz"
EVENTS_GZ="${SEED_DIR}/events.csv.gz"

PGHOST="${DATABASE_HOST:-${PGHOST:-localhost}}"
PGPORT="${DATABASE_PORT:-${PGPORT:-5432}}"
PGUSER="${DATABASE_USER:-${PGUSER:-hack_max}}"
PGDATABASE="${DATABASE_NAME:-${PGDATABASE:-hack_max}}"
export PGPASSWORD="${DATABASE_PASSWORD:-${PGPASSWORD:-hack_max}}"
export PGHOST PGPORT PGUSER PGDATABASE

psql_cmd() {
  psql -v ON_ERROR_STOP=1 --no-psqlrc "$@"
}

table_has_rows() {
  local table="$1"
  local n
  n="$(psql_cmd -Atc "SELECT CASE WHEN EXISTS (SELECT 1 FROM ${table} LIMIT 1) THEN 1 ELSE 0 END")"
  [[ "$n" == "1" ]]
}

load_csv() {
  local table="$1"
  local gz="$2"
  local columns="$3"

  if [[ ! -f "$gz" ]]; then
    echo "WARN: $gz отсутствует — пропуск seed ${table}"
    return 0
  fi
  if table_has_rows "$table"; then
    echo "${table}: уже есть данные — пропуск COPY"
    return 0
  fi

  echo "Loading ${table} from ${gz} ..."
  gunzip -c "$gz" | psql_cmd -c "\\copy ${table} (${columns}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '\\N')"
  psql_cmd -c "SELECT setval(pg_get_serial_sequence('${table}', 'id'), COALESCE((SELECT MAX(id) FROM ${table}), 1));"
  echo "${table}: done"
}

load_csv addresses "$ADDR_GZ" \
  "id, postal_code, address_text, city, district, street, house, latitude, longitude, is_private"

load_csv events "$EVENTS_GZ" \
  "id, title, body, importance, source, address_id, geo_by, weight, source_msg_id, disaster_flag, source_url, image_url, published_at, active_from, active_to, created_at, updated_at"

echo "pg seed: ok"
