ALTER TABLE users_chat
    DROP COLUMN IF EXISTS address_id;

DROP INDEX IF EXISTS ix_chat_addresses_address_id;
DROP TABLE IF EXISTS chat_addresses;
