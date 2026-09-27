-- Несколько личных адресов подтверждённого участника одного домового чата.
CREATE TABLE user_chat_addresses (
    user_id INTEGER NOT NULL,
    chat_id BIGINT NOT NULL,
    address_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, chat_id, address_id),
    FOREIGN KEY (user_id, chat_id) REFERENCES users_chat(user_id, chat_id) ON DELETE CASCADE,
    FOREIGN KEY (chat_id, address_id) REFERENCES chat_addresses(chat_id, address_id) ON DELETE CASCADE
);

-- Существующие личные выборы сохраняем, не присваивая пользователям все дома группы.
INSERT INTO user_chat_addresses (user_id, chat_id, address_id)
SELECT uc.user_id, uc.chat_id, uc.address_id
FROM users_chat AS uc
JOIN chat_addresses AS ca
    ON ca.chat_id = uc.chat_id AND ca.address_id = uc.address_id
WHERE uc.address_id IS NOT NULL;
