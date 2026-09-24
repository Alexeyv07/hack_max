-- 0006_news_parser.up.sql
CREATE TABLE news_parser_cursors (
    source_key VARCHAR(64) PRIMARY KEY,
    backfill_complete BOOLEAN NOT NULL DEFAULT false,
    oldest_seen_at TIMESTAMPTZ,
    newest_seen_at TIMESTAMPTZ,
    listing_cursor VARCHAR(512),
    last_run_at TIMESTAMPTZ,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_events_source_msg
    ON events (source, source_msg_id)
    WHERE source_msg_id IS NOT NULL;
