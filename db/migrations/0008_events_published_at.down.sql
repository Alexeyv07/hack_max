-- 0008_events_published_at.down.sql
DROP INDEX IF EXISTS ix_events_published_at;
ALTER TABLE events DROP COLUMN IF EXISTS published_at;
