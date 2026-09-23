-- 0013_events_active_window.down.sql
DROP INDEX IF EXISTS ix_events_active_to;
DROP INDEX IF EXISTS ix_events_active_from;
ALTER TABLE events DROP COLUMN IF EXISTS active_to;
ALTER TABLE events DROP COLUMN IF EXISTS active_from;
