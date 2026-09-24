-- 0009_create_chats.down.sql
DROP INDEX IF EXISTS ix_users_chat_chat_id;
DROP TABLE IF EXISTS users_chat;
DROP INDEX IF EXISTS ix_chats_address_id;
DROP TABLE IF EXISTS chats;
