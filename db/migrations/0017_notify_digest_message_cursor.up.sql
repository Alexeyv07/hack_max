-- Cursor последнего суммаризированного сообщения (ex-alembic 0015).

ALTER TABLE notify_digests
    ADD COLUMN last_message_at TIMESTAMPTZ;
