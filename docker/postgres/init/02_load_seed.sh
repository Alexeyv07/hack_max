#!/bin/bash
# Загрузка addresses + events через COPY (без Python).
# Файлы: /seed/addresses.csv.gz, /seed/events.csv.gz
set -euo pipefail

SEED_DIR="${SEED_DIR:-/seed}"
ADDR_GZ="${SEED_DIR}/addresses.csv.gz"
EVENTS_GZ="${SEED_DIR}/events.csv.gz"

if [[ ! -f "$ADDR_GZ" ]]; then
  echo "WARN: $ADDR_GZ отсутствует — пропуск seed адресов"
  exit 0
fi

echo "Loading addresses from $ADDR_GZ ..."
gunzip -c "$ADDR_GZ" > /tmp/addresses.csv
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
COPY addresses (
  id, postal_code, address_text, city, district, street, house,
  latitude, longitude, is_private
) FROM '/tmp/addresses.csv' WITH (FORMAT csv, HEADER true, NULL '\N');
SELECT setval(
  pg_get_serial_sequence('addresses', 'id'),
  COALESCE((SELECT MAX(id) FROM addresses), 1)
);
SQL
rm -f /tmp/addresses.csv
echo "addresses: done"

if [[ ! -f "$EVENTS_GZ" ]]; then
  echo "WARN: $EVENTS_GZ отсутствует — пропуск seed событий"
  exit 0
fi

echo "Loading events from $EVENTS_GZ ..."
gunzip -c "$EVENTS_GZ" > /tmp/events.csv
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
COPY events (
  id, title, body, importance, source, address_id, geo_by, weight,
  source_msg_id, disaster_flag, source_url, image_url,
  published_at, active_from, active_to, created_at, updated_at
) FROM '/tmp/events.csv' WITH (FORMAT csv, HEADER true, NULL '\N');
SELECT setval(
  pg_get_serial_sequence('events', 'id'),
  COALESCE((SELECT MAX(id) FROM events), 1)
);
SQL
rm -f /tmp/events.csv
echo "events: done"
