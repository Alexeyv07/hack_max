-- Сохраняем mid последнего отправленного priority-уведомления,
-- чтобы при повторе (spam до «Увидел») удалять предыдущее сообщение в чате.

ALTER TABLE notify_deliveries
    ADD COLUMN IF NOT EXISTS last_message_mid VARCHAR(255);
