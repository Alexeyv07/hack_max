# Чаты соседей (KAN-5)

Модуль `user_chat` хранит чаты и членство пользователей (KAN-5). Его handlers вызываются ботом или
другими модулями внутри процесса; HTTP и синхронизация участников через MAX API
не входят в эту задачу. Onboarding-flow относится к отдельному `chat_link` (KAN-7).

## Таблицы

```text
users.id  ← users_chat.user_id
               users_chat.chat_id → chats.chat_id
                                      chats.address_id → addresses.id
```

- `chats.chat_id` — PK, signed BigInteger, реальный MAX chat_id. Отдельный локальный
  id не нужен. Именование сохранено из `ChatMembership` и кода MAX-событий.
- `chats.title` — название; `invite_link` — отдельная необязательная ссылка.
  `chat_type='chat'` помечает подтверждённую групповую MAX-сущность. `NULL` оставлен
  для legacy-записей старого mock-flow и не считается домовым чатом.
  В `maxapi` chat_id — int, ссылка `Chat.link` может быть None.
- `address_id` — обязательный FK с `ON DELETE RESTRICT`, обычный неуникальный индекс.
  На один дом допускается несколько чатов. Координаты и текст адреса не копируются.
- `users_chat` — association table с PK `(user_id, chat_id)`, где `user_id` —
  **внутренний `users.id`**. Повторная пара запрещена на уровне БД. Для выборки
  участников есть индекс по `chat_id`.
- У FK таблицы связей `ON DELETE CASCADE`: удаление пользователя или чата очищает
  только membership. Удаление чата не удаляет пользователей или адрес.
- `users.chat_id` из auth — контекст взаимодействия с ботом. Он не используется
  для автоматического создания membership и не переносится миграцией в `users_chat`.

Миграция: `0008_events_published_at → 0009_create_chats`.

## Вызовы

```python
from user_chat.handlers import create_chat, add_user_to_chat, list_memberships_for_user
from user_chat.models import ChatCreate
from project.database import session_scope

with session_scope() as session:
    chat = create_chat(
        session,
        ChatCreate(
            chat_id=max_chat_id,
            address_id=address_id,
            title="Наш дом",
            invite_link=invite_link,  # str или None
        ),
    )
    added = add_user_to_chat(session, chat.chat_id, max_user_id=max_user_id)
    memberships = list_memberships_for_user(session, max_user_id)
```

Адрес и зарегистрированный пользователь должны уже существовать. Вызывающий
модуль отвечает за подтверждение присоединения пользователя к MAX-чату.
Handlers не коммитят: границу транзакции задаёт `session_scope` или вызывающий код.

| Handler | Результат |
| --- | --- |
| `create_chat(session, ChatCreate(...))` | `Chat`; неизвестный адрес или существующий chat_id → ValueError |
| `get_chat(session, chat_id)` | `Chat` либо None |
| `detach_chat(session, chat_id)` | помечает чат `removed`, очищает invite link и все локальные membership после `bot_removed` |
| `list_chats_by_address(session, address_id)` | подтверждённые групповые чаты адреса, включая пустые |
| `add_user_to_chat(session, chat_id, max_user_id=...)` | True при добавлении, False при повторе; неизвестный пользователь/чат → ValueError |
| `bind_known_chat_member(session, chat_id, max_user_id=...)` | то же persistence после внешней проверки реального membership в MAX |
| `remove_user_from_chat(session, chat_id, max_user_id=...)` | True при удалении связи, False при её отсутствии |
| `list_chat_members(session, chat_id)` | список `ChatMember`; неизвестный/пустой чат → [] |
| `list_memberships_for_user(session, max_user_id)` | `ChatMembership` только для подтверждённых групп; legacy DIALOG не учитывается |

Добавление использует `INSERT ... ON CONFLICT DO NOTHING`, поэтому параллельные
повторы также не создают дубль. PK/FK остаются последней защитой от гонок;
конкурирующее создание того же чата может завершиться IntegrityError.
Радиусы ленты/карты берутся из существующих настроек `events`, координаты — из
актуальной связанной записи `Address`.

## Проверка

`python -m pytest` запускает SQLite-тесты с включёнными FK. Для проверки полной
цепочки миграций и PostgreSQL-ветки handlers задайте `ADDRESS_TEST_DATABASE_URL`
тестовой PostgreSQL с правом `CREATE SCHEMA`. Тесты создают отдельные схемы и
откатывают изменения.
