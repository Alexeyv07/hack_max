-- 0012_chat_group_type.down.sql
DROP INDEX IF EXISTS ix_chats_chat_type;
ALTER TABLE chats DROP COLUMN IF EXISTS chat_type;
