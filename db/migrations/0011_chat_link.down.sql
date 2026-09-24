-- 0011_chat_link.down.sql
DROP INDEX IF EXISTS ix_chat_links_status;
DROP INDEX IF EXISTS ix_chat_links_address;
DROP INDEX IF EXISTS ix_chat_links_requester;
DROP TABLE IF EXISTS chat_links;
DROP INDEX IF EXISTS ix_addresses_district;
ALTER TABLE addresses DROP COLUMN IF EXISTS district;
