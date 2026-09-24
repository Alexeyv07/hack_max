-- Блокировка личных пушей при недоступном диалоге MAX (ex-alembic 0018).

ALTER TABLE users
    ADD COLUMN notify_blocked_at TIMESTAMPTZ,
    ADD COLUMN notify_blocked_reason VARCHAR(128);
