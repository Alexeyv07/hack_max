-- 0002_create_events.down.sql
DROP INDEX IF EXISTS ix_events_source_msg_id;
DROP INDEX IF EXISTS ix_events_weight;
DROP INDEX IF EXISTS ix_events_source;
DROP INDEX IF EXISTS ix_events_importance;
DROP TABLE IF EXISTS events;
