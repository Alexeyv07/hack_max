#!/bin/sh
# Initdb: COPY addresses + events из /seed/*.csv.gz (после миграций).
set -eu

SEED_DIR="${SEED_DIR:-/seed}"
ADDR_GZ="${SEED_DIR}/addresses.csv.gz"
EVENTS_GZ="${SEED_DIR}/events.csv.gz"

table_has_rows() {
  table="$1"
  n=$(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -Atc \
    "SELECT CASE WHEN EXISTS (SELECT 1 FROM ${table} LIMIT 1) THEN 1 ELSE 0 END")
  [ "$n" = "1" ]
}

load_csv() {
  table="$1"
  gz="$2"
  columns="$3"

  if [ ! -f "$gz" ]; then
    echo "WARN: $gz missing — skip ${table}"
    return 0
  fi
  if table_has_rows "$table"; then
    echo "${table}: already seeded — skip"
    return 0
  fi

  echo "Loading ${table} from ${gz} ..."
  gunzip -c "$gz" > "/tmp/${table}.csv"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c \
    "COPY ${table} (${columns}) FROM '/tmp/${table}.csv' WITH (FORMAT csv, HEADER true, NULL '\\N');"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c \
    "SELECT setval(pg_get_serial_sequence('${table}', 'id'), COALESCE((SELECT MAX(id) FROM ${table}), 1));"
  rm -f "/tmp/${table}.csv"
  echo "${table}: done"
}

load_csv addresses "$ADDR_GZ" \
  "id, postal_code, address_text, city, district, street, house, latitude, longitude, is_private"

load_csv events "$EVENTS_GZ" \
  "id, title, body, importance, source, address_id, geo_by, weight, source_msg_id, disaster_flag, source_url, image_url, published_at, active_from, active_to, created_at, updated_at"

echo "seed: ok"
