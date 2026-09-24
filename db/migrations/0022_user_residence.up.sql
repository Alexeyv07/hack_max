-- Личный адрес пользователя: новости работают без подключения группового чата.
ALTER TABLE users
    ADD COLUMN address_id INTEGER REFERENCES addresses(id) ON DELETE RESTRICT;
CREATE INDEX ix_users_address_id ON users (address_id);

-- Сохранить выбранный дом существующих участников при обновлении старой БД.
-- При нескольких чатах выбираем определённо первый; пользователь сможет сменить адрес.
UPDATE users AS u SET address_id = (
    SELECT uc.address_id FROM users_chat AS uc
    WHERE uc.user_id = u.id AND uc.address_id IS NOT NULL
    ORDER BY uc.chat_id LIMIT 1
)
WHERE u.address_id IS NULL;
