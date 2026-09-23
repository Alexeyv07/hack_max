-- 0012_chat_group_type.up.sql
ALTER TABLE chats ADD COLUMN chat_type VARCHAR(16);
CREATE INDEX ix_chats_chat_type ON chats (chat_type);

UPDATE chats
SET chat_type = 'chat'
WHERE chat_id IN (
    SELECT DISTINCT chat_id
    FROM chat_links
    WHERE chat_id IS NOT NULL
      AND status IN ('connected', 'waiting_join')
);
