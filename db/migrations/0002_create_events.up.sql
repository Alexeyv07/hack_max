-- 0002_create_events.up.sql
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    title VARCHAR(512) NOT NULL,
    body TEXT NOT NULL,
    importance INTEGER NOT NULL,
    source VARCHAR(64) NOT NULL,
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    weight DOUBLE PRECISION NOT NULL DEFAULT 0,
    source_msg_id VARCHAR(128),
    disaster_flag BOOLEAN NOT NULL DEFAULT false,
    source_url VARCHAR(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_events_importance ON events (importance);
CREATE INDEX ix_events_source ON events (source);
CREATE INDEX ix_events_weight ON events (weight);
CREATE INDEX ix_events_source_msg_id ON events (source_msg_id);
