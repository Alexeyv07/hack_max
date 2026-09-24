-- Notify: deliveries, digests, event cursor (ex-alembic 0014_notify_workers).

CREATE TABLE notify_deliveries (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    attempts INTEGER NOT NULL DEFAULT 0,
    first_sent_at TIMESTAMPTZ,
    last_sent_at TIMESTAMPTZ,
    acked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_notify_delivery_user_event UNIQUE (user_id, event_id)
);

CREATE INDEX ix_notify_deliveries_user_id ON notify_deliveries (user_id);
CREATE INDEX ix_notify_deliveries_event_id ON notify_deliveries (event_id);
CREATE INDEX ix_notify_deliveries_acked_at ON notify_deliveries (acked_at);
CREATE INDEX ix_notify_deliveries_last_sent_at ON notify_deliveries (last_sent_at);

CREATE TABLE notify_digests (
    chat_id BIGINT PRIMARY KEY REFERENCES chats(chat_id) ON DELETE CASCADE,
    last_digest_date DATE,
    last_sent_at TIMESTAMPTZ
);

CREATE TABLE notify_cursors (
    name VARCHAR PRIMARY KEY,
    last_event_id INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
