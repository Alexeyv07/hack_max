-- 0010_mc_parser.up.sql
CREATE TABLE mc_parser_cursors (
    source_key VARCHAR(64) PRIMARY KEY,
    backfill_complete BOOLEAN NOT NULL DEFAULT false,
    oldest_seen_at TIMESTAMPTZ,
    newest_seen_at TIMESTAMPTZ,
    listing_cursor VARCHAR(512),
    last_run_at TIMESTAMPTZ,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
