DROP INDEX IF EXISTS ix_users_address_id;
ALTER TABLE users DROP COLUMN IF EXISTS address_id;
