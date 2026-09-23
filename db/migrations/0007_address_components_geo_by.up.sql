-- 0007_address_components_geo_by.up.sql
ALTER TABLE addresses ADD COLUMN city VARCHAR(128);
ALTER TABLE addresses ADD COLUMN street VARCHAR(512);
ALTER TABLE addresses ADD COLUMN house VARCHAR(64);
CREATE INDEX ix_addresses_city ON addresses (city);

ALTER TABLE events ADD COLUMN geo_by VARCHAR(16);
CREATE INDEX ix_events_geo_by ON events (geo_by);

-- Best-effort backfill (полный разбор — в seed CSV / address.seed).
UPDATE addresses
SET city = NULLIF(trim(split_part(address_text, ',', 1)), '')
WHERE city IS NULL;
