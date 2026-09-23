-- 0013_events_active_window.up.sql
ALTER TABLE events ADD COLUMN active_from TIMESTAMPTZ;
ALTER TABLE events ADD COLUMN active_to TIMESTAMPTZ;
CREATE INDEX ix_events_active_from ON events (active_from);
CREATE INDEX ix_events_active_to ON events (active_to);
