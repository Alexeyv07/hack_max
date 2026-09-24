#!/bin/sh
# Initdb: накатить все *.up.sql в schema_migrations.
set -eu

MIGRATIONS_DIR="${MIGRATIONS_DIR:-/migrations}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
SQL

for up in "$MIGRATIONS_DIR"/*.up.sql; do
  [ -f "$up" ] || continue
  base=$(basename "$up")
  version=${base%.up.sql}
  applied=$(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -Atc \
    "SELECT 1 FROM schema_migrations WHERE version = '${version}'")
  if [ "$applied" = "1" ]; then
    echo "migrate skip: $version"
    continue
  fi
  echo "migrate UP: $version"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$up"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c \
    "INSERT INTO schema_migrations (version) VALUES ('${version}');"
done

echo "migrate: done"
