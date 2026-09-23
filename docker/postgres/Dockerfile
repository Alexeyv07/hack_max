# Postgres: SQL-миграции (db/migrations) + COPY seed на первом initdb.
FROM postgres:16-alpine

COPY db/migrations /migrations
COPY docker/postgres/init/00_migrate.sh /docker-entrypoint-initdb.d/00_migrate.sh
COPY docker/postgres/init/01_load_seed.sh /docker-entrypoint-initdb.d/01_load_seed.sh
COPY docker/postgres/seed /seed

RUN chmod +x /docker-entrypoint-initdb.d/00_migrate.sh \
             /docker-entrypoint-initdb.d/01_load_seed.sh \
    && sed -i 's/\r$//' /docker-entrypoint-initdb.d/*.sh
