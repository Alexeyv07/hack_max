-- 0009_create_chats.up.sql
CREATE TABLE chats (
    chat_id BIGINT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    invite_link VARCHAR(2048),
    address_id INTEGER NOT NULL REFERENCES addresses (id) ON DELETE RESTRICT
);

CREATE INDEX ix_chats_address_id ON chats (address_id);

CREATE TABLE users_chat (
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL REFERENCES chats (chat_id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, chat_id)
);

CREATE INDEX ix_users_chat_chat_id ON users_chat (chat_id);
