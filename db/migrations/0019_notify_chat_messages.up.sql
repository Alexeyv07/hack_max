-- Сообщения чата для #итого (ex-alembic 0017_notify_chat_messages).

CREATE TABLE notify_chat_messages (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
    message_id VARCHAR(255) NOT NULL,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_notify_chat_message_chat_mid UNIQUE (chat_id, message_id)
);

CREATE INDEX ix_notify_chat_messages_chat_id_id ON notify_chat_messages (chat_id, id);

ALTER TABLE notify_digests
    ADD COLUMN last_message_id INTEGER;
