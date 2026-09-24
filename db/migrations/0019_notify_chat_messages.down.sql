ALTER TABLE notify_digests
    DROP COLUMN IF EXISTS last_message_id;

DROP INDEX IF EXISTS ix_notify_chat_messages_chat_id_id;
DROP TABLE IF EXISTS notify_chat_messages;
