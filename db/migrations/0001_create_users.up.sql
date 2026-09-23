-- 0001_create_users.up.sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    max_user_id BIGINT NOT NULL,
    name VARCHAR(255),
    username VARCHAR(255),
    chat_id BIGINT,
    start_payload VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ix_users_max_user_id ON users (max_user_id);
CREATE INDEX ix_users_username ON users (username);
