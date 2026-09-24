-- 0005_event_address_fk.up.sql
ALTER TABLE events ADD COLUMN address_id INTEGER;
CREATE INDEX ix_events_address_id ON events (address_id);
ALTER TABLE events
    ADD CONSTRAINT fk_events_address_id_addresses
    FOREIGN KEY (address_id) REFERENCES addresses (id) ON DELETE SET NULL;

-- Если старые mock-events совпадают ровно с одной точкой справочника.
WITH unique_coordinates AS (
    SELECT
        latitude::double precision AS lat,
        longitude::double precision AS lon,
        min(id) AS address_id
    FROM addresses
    GROUP BY latitude, longitude
    HAVING count(*) = 1
)
UPDATE events AS event
SET address_id = point.address_id
FROM unique_coordinates AS point
WHERE event.lat = point.lat AND event.lon = point.lon;

ALTER TABLE events DROP COLUMN IF EXISTS lat;
ALTER TABLE events DROP COLUMN IF EXISTS lon;
