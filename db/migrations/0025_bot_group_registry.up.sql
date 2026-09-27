-- Реестр групп, где бот присутствует; связь с адресом остаётся в chats/chat_addresses.
CREATE TABLE bot_group_registry (
    chat_id BIGINT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    added_by_user_id BIGINT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_bot_group_registry_active ON bot_group_registry (is_active);

-- Уже подключённые группы не теряются после внедрения реестра.
INSERT INTO bot_group_registry (chat_id, title, is_active)
SELECT chat_id, title, TRUE FROM chats WHERE chat_type = 'chat';
