-- Закрыть незавершённые заявки старого admin approve (ex-alembic 0016).

UPDATE chat_links
SET status = 'cancelled'
WHERE status IN ('waiting_approval', 'approval_sent');
