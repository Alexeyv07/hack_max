-- Запоминаем порядок добавления личных адресов для карты.
ALTER TABLE user_chat_addresses
    ADD COLUMN added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
