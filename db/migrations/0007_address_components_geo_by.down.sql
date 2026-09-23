-- 0007_address_components_geo_by.down.sql
DROP INDEX IF EXISTS ix_events_geo_by;
ALTER TABLE events DROP COLUMN IF EXISTS geo_by;
DROP INDEX IF EXISTS ix_addresses_city;
ALTER TABLE addresses DROP COLUMN IF EXISTS house;
ALTER TABLE addresses DROP COLUMN IF EXISTS street;
ALTER TABLE addresses DROP COLUMN IF EXISTS city;
