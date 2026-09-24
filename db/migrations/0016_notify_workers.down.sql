DROP TABLE IF EXISTS notify_cursors;
DROP TABLE IF EXISTS notify_digests;
DROP INDEX IF EXISTS ix_notify_deliveries_last_sent_at;
DROP INDEX IF EXISTS ix_notify_deliveries_acked_at;
DROP INDEX IF EXISTS ix_notify_deliveries_event_id;
DROP INDEX IF EXISTS ix_notify_deliveries_user_id;
DROP TABLE IF EXISTS notify_deliveries;
