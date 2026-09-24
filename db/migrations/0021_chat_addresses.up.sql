-- Несколько адресов на группу + выбранный дом участника (ex-alembic 0019).

CREATE TABLE chat_addresses (
    chat_id BIGINT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
    address_id INTEGER NOT NULL REFERENCES addresses(id) ON DELETE RESTRICT,
    PRIMARY KEY (chat_id, address_id)
);

CREATE INDEX ix_chat_addresses_address_id ON chat_addresses (address_id);

INSERT INTO chat_addresses (chat_id, address_id)
SELECT chat_id, address_id FROM chats;

ALTER TABLE users_chat
    ADD COLUMN address_id INTEGER REFERENCES addresses(id) ON DELETE RESTRICT;

-- Уже подключённым пользователям оставляем адрес чата.
UPDATE users_chat
SET address_id = (
    SELECT chats.address_id FROM chats WHERE chats.chat_id = users_chat.chat_id
);
