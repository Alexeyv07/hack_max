-- 0008_events_published_at.up.sql
ALTER TABLE events ADD COLUMN published_at TIMESTAMPTZ;
CREATE INDEX ix_events_published_at ON events (published_at);
