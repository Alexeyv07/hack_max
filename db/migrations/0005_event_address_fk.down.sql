-- 0005_event_address_fk.down.sql
ALTER TABLE events ADD COLUMN lon DOUBLE PRECISION;
ALTER TABLE events ADD COLUMN lat DOUBLE PRECISION;

UPDATE events AS event
SET
    lat = address.latitude::double precision,
    lon = address.longitude::double precision
FROM addresses AS address
WHERE event.address_id = address.id;

ALTER TABLE events DROP CONSTRAINT IF EXISTS fk_events_address_id_addresses;
DROP INDEX IF EXISTS ix_events_address_id;
ALTER TABLE events DROP COLUMN IF EXISTS address_id;
