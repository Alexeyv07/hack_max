ALTER TABLE users
    DROP COLUMN IF EXISTS notify_blocked_reason,
    DROP COLUMN IF EXISTS notify_blocked_at;
