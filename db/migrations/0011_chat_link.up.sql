-- 0011_chat_link.up.sql
ALTER TABLE addresses ADD COLUMN district VARCHAR(256);
CREATE INDEX ix_addresses_district ON addresses (district);

CREATE TABLE chat_links (
    id SERIAL PRIMARY KEY,
    token VARCHAR(32) NOT NULL,
    requester_user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    admin_user_id INTEGER REFERENCES users (id) ON DELETE SET NULL,
    address_id INTEGER NOT NULL REFERENCES addresses (id) ON DELETE RESTRICT,
    chat_id BIGINT REFERENCES chats (chat_id) ON DELETE SET NULL,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_chat_links_token UNIQUE (token)
);

CREATE INDEX ix_chat_links_requester ON chat_links (requester_user_id);
CREATE INDEX ix_chat_links_address ON chat_links (address_id);
CREATE INDEX ix_chat_links_status ON chat_links (status);
