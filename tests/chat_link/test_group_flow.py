from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from maxapi.enums import ChatType

from address.db import AddressRow
from auth.handlers.authorize import authorize_user
from auth.models.user import MaxUserPayload
from chat_link.handlers import (
    announce_connected_group,
    bind_referral_member,
    bot_can_read_group,
    claim_admin_request,
    connect_added_group,
    connect_added_group_to_address,
    connect_group_chat,
    connected_group_address,
    create_request,
    existing_group_chats,
    join_existing_chat,
    pending_for_actor,
)
from chat_link.models import ChatLinkStatus
from user_chat.handlers import (
    create_chat,
    get_chat,
    list_chat_addresses,
    list_chat_members,
    list_memberships_for_user,
)
from user_chat.models import ChatCreate


class FakeBot:
    def __init__(
        self,
        *,
        admins: set[int] | None = None,
        members: set[int] | None = None,
        bot_admin: bool = False,
        bot_permissions: list[str] | None = None,
        chat_type: ChatType = ChatType.CHAT,
    ) -> None:
        self.admins = set(admins or set())
        self.members = set(members or set()) | self.admins
        self.add_success = True
        self.bot_admin = bot_admin
        self.bot_permissions = list(bot_permissions or [])
        self.chat_type = chat_type
        self.add_calls: list[tuple[int, tuple[int, ...]]] = []

    async def get_chat_member(self, chat_id: int, max_user_id: int):
        if max_user_id not in self.members:
            return None
        return SimpleNamespace(
            user_id=max_user_id,
            is_admin=max_user_id in self.admins,
            is_owner=False,
        )

    async def add_chat_members(self, chat_id: int, user_ids: list[int]):
        self.add_calls.append((chat_id, tuple(user_ids)))
        if self.add_success:
            self.members.update(user_ids)
        return SimpleNamespace(success=self.add_success)

    async def get_chat_by_id(self, chat_id: int):
        return SimpleNamespace(
            chat_id=chat_id,
            type=self.chat_type,
            title="Домовой чат",
            link="https://max.ru/join/house",
        )

    async def get_me_from_chat(self, chat_id: int):
        return SimpleNamespace(
            is_admin=self.bot_admin,
            is_owner=False,
            permissions=self.bot_permissions,
        )


def _address(db_session) -> AddressRow:
    row = AddressRow(
        address_text="Москва, район Тестовый, улица Соседская, д. 1",
        city="Москва",
        district="район Тестовый",
        street="улица Соседская",
        house="1",
        latitude=Decimal("55.7500000"),
        longitude=Decimal("37.6100000"),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _user(db_session, max_user_id: int):
    return authorize_user(
        db_session,
        MaxUserPayload(max_user_id=max_user_id, name=f"User {max_user_id}"),
    )


def test_admin_connects_new_real_group(db_session) -> None:
    address = _address(db_session)
    admin = _user(db_session, 101)
    request, chats = create_request(
        db_session,
        max_user_id=admin.max_user_id,
        address_id=address.id,
    )
    assert chats == []
    assert request.status is ChatLinkStatus.WAITING_GROUP

    outcome = asyncio.run(
        connect_group_chat(
            FakeBot(admins={101}),
            db_session,
            token=request.token,
            chat_id=-9001,
            admin_max_user_id=101,
        )
    )

    assert outcome.connected
    assert outcome.requester_added
    assert get_chat(db_session, -9001).address_id == address.id
    assert [member.max_user_id for member in list_chat_members(db_session, -9001)] == [101]


def test_added_group_connects_from_actor_without_command(db_session) -> None:
    address = _address(db_session)
    admin = _user(db_session, 101)
    request, _ = create_request(
        db_session,
        max_user_id=admin.max_user_id,
        address_id=address.id,
    )

    outcome = asyncio.run(
        connect_added_group(
            FakeBot(admins={101}),
            db_session,
            chat_id=-9010,
            actor_max_user_id=101,
        )
    )

    assert outcome.connected
    assert get_chat(db_session, -9010).address_id == request.address_id
    assert [member.max_user_id for member in list_chat_members(db_session, -9010)] == [101]


def test_added_group_can_choose_address_after_bot_was_added(db_session) -> None:
    address = _address(db_session)
    admin = _user(db_session, 101)
    bot = FakeBot(
        admins={101},
        bot_admin=True,
        bot_permissions=["read_all_messages"],
    )

    outcome = asyncio.run(
        connect_added_group_to_address(
            bot,
            db_session,
            chat_id=-9020,
            admin_max_user_id=admin.max_user_id,
            address_id=address.id,
        )
    )

    assert outcome.connected
    assert outcome.requester_added
    assert get_chat(db_session, -9020).address_id == address.id
    assert [member.max_user_id for member in list_chat_members(db_session, -9020)] == [101]


def test_added_group_rejects_address_that_already_has_chat(db_session) -> None:
    address = _address(db_session)
    admin = _user(db_session, 101)
    create_chat(
        db_session,
        ChatCreate(chat_id=-9021, address_id=address.id, title="Уже подключённый чат"),
    )
    bot = FakeBot(
        admins={101},
        bot_admin=True,
        bot_permissions=["read_all_messages"],
    )

    outcome = asyncio.run(
        connect_added_group_to_address(
            bot,
            db_session,
            chat_id=-9022,
            admin_max_user_id=admin.max_user_id,
            address_id=address.id,
        )
    )

    assert not outcome.connected
    assert "уже подключён" in (outcome.message or "")
    assert get_chat(db_session, -9022) is None


def test_bot_group_readiness_requires_admin_and_read_all_messages() -> None:
    assert not asyncio.run(bot_can_read_group(FakeBot(), -9011))
    assert not asyncio.run(bot_can_read_group(FakeBot(bot_admin=True), -9011))
    assert asyncio.run(
        bot_can_read_group(
            FakeBot(bot_admin=True, bot_permissions=["read_all_messages"]),
            -9011,
        )
    )


def test_forwarded_admin_link_claims_request_without_auto_adding_requester(db_session) -> None:
    address = _address(db_session)
    requester = _user(db_session, 101)
    _user(db_session, 202)
    request, _ = create_request(
        db_session,
        max_user_id=requester.max_user_id,
        address_id=address.id,
    )

    claim_admin_request(db_session, token=request.token, max_user_id=202)
    pending = pending_for_actor(db_session, 202)
    assert pending is not None
    assert pending.token == request.token

    bot = FakeBot(admins={202})
    outcome = asyncio.run(
        connect_group_chat(
            bot,
            db_session,
            token=request.token,
            chat_id=-9002,
            admin_max_user_id=202,
        )
    )

    assert outcome.connected
    assert not outcome.requester_added
    assert {member.max_user_id for member in list_chat_members(db_session, -9002)} == {202}
    assert bot.add_calls == []


def test_pending_for_actor_prefers_latest_explicit_admin_claim(db_session) -> None:
    own_address = _address(db_session)
    admin = _user(db_session, 202)
    own_request, _ = create_request(
        db_session,
        max_user_id=admin.max_user_id,
        address_id=own_address.id,
    )

    delegated_address = AddressRow(
        address_text="Москва, район Тестовый, улица Соседская, д. 2",
        city="Москва",
        district="район Тестовый",
        street="улица Соседская",
        house="2",
        latitude=Decimal("55.7501000"),
        longitude=Decimal("37.6101000"),
    )
    db_session.add(delegated_address)
    db_session.flush()
    requester = _user(db_session, 303)
    delegated_request, _ = create_request(
        db_session,
        max_user_id=requester.max_user_id,
        address_id=delegated_address.id,
    )
    claim_admin_request(
        db_session,
        token=delegated_request.token,
        max_user_id=admin.max_user_id,
    )

    selected = pending_for_actor(db_session, admin.max_user_id)
    assert selected is not None
    assert selected.token == delegated_request.token
    assert selected.token != own_request.token


def test_existing_chat_does_not_auto_add_user(db_session) -> None:
    address = _address(db_session)
    user = _user(db_session, 101)
    create_chat(
        db_session,
        ChatCreate(
            chat_id=-9003,
            address_id=address.id,
            title="Соседи",
            invite_link="https://max.ru/join/existing",
        ),
    )
    request, chats = create_request(
        db_session,
        max_user_id=user.max_user_id,
        address_id=address.id,
    )
    assert [chat.chat_id for chat in chats] == [-9003]
    assert request.status is ChatLinkStatus.WAITING_JOIN

    bot = FakeBot()
    outcome = asyncio.run(
        join_existing_chat(
            bot,
            db_session,
            token=request.token,
            chat_id=-9003,
            max_user_id=101,
        )
    )

    assert not outcome.joined
    assert outcome.invite_link is None
    assert "не состоите" in outcome.message
    assert bot.add_calls == []
    assert list_chat_members(db_session, -9003) == []


def test_existing_chat_persists_only_after_real_membership(db_session) -> None:
    address = _address(db_session)
    user = _user(db_session, 101)
    create_chat(
        db_session,
        ChatCreate(
            chat_id=-9004,
            address_id=address.id,
            title="Соседи",
            invite_link="https://max.ru/join/fallback",
        ),
    )
    request, _ = create_request(
        db_session,
        max_user_id=user.max_user_id,
        address_id=address.id,
    )
    bot = FakeBot(members={101})

    outcome = asyncio.run(
        join_existing_chat(
            bot,
            db_session,
            token=request.token,
            chat_id=-9004,
            max_user_id=101,
        )
    )

    assert outcome.joined
    assert bot.add_calls == []
    assert [member.max_user_id for member in list_chat_members(db_session, -9004)] == [101]


def test_existing_group_chats_filters_legacy_dialogs(db_session) -> None:
    address = _address(db_session)
    real = create_chat(
        db_session,
        ChatCreate(
            chat_id=-9100,
            address_id=address.id,
            title="Группа",
            invite_link="https://max.ru/join/group",
        ),
    )
    dialog = create_chat(
        db_session,
        ChatCreate(
            chat_id=9101,
            address_id=address.id,
            title="Старый dialog mock",
            chat_type="chat",
        ),
    )

    class MixedBot(FakeBot):
        async def get_chat_by_id(self, chat_id: int):
            return SimpleNamespace(
                chat_id=chat_id,
                type=ChatType.CHAT if chat_id == real.chat_id else ChatType.DIALOG,
                title="Домовой чат" if chat_id == real.chat_id else "Личный диалог",
                link="https://max.ru/join/live" if chat_id == real.chat_id else None,
            )

    groups = asyncio.run(existing_group_chats(MixedBot(), [real, dialog]))
    assert [chat.chat_id for chat in groups] == [real.chat_id]
    assert groups[0].invite_link == "https://max.ru/join/live"


def test_referral_binds_only_after_max_membership(db_session) -> None:
    address = _address(db_session)
    user = _user(db_session, 101)
    create_chat(
        db_session,
        ChatCreate(chat_id=-9005, address_id=address.id, title="Соседи"),
    )

    outside = asyncio.run(
        bind_referral_member(
            FakeBot(),
            db_session,
            chat_id=-9005,
            max_user_id=user.max_user_id,
        )
    )
    assert not outside.joined
    assert list_chat_members(db_session, -9005) == []

    inside = asyncio.run(
        bind_referral_member(
            FakeBot(members={101}),
            db_session,
            chat_id=-9005,
            max_user_id=user.max_user_id,
        )
    )
    assert inside.joined
    assert [member.max_user_id for member in list_chat_members(db_session, -9005)] == [101]


def test_group_announcement_edits_same_message_after_address_added(db_session, monkeypatch) -> None:
    from contextlib import contextmanager

    import chat_link.handlers.group as group
    from project.bot_media import FIRST_START_IMAGE_PATH
    from user_chat.db import ChatRow
    from user_chat.handlers import add_chat_address, remove_chat_address

    @contextmanager
    def same_session():
        yield db_session

    monkeypatch.setattr(group, "session_scope", same_session)
    first = _address(db_session)
    create_chat(db_session, ChatCreate(chat_id=-9001, address_id=first.id, chat_type="chat"))
    sent = SimpleNamespace(message=SimpleNamespace(body=SimpleNamespace(mid="group-mid")))
    bot = SimpleNamespace(
        me=SimpleNamespace(username=None),
        send_message=AsyncMock(return_value=sent),
        edit_message=AsyncMock(),
    )
    asyncio.run(announce_connected_group(bot, -9001, address_text=first.address_text))
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["text"].startswith(f"Домовой чат по адресу:\n• {first.address_text}\n\n")
    assert "✅ Подключён к сервису окружающих вас новостей «Касается меня»." in kwargs["text"]
    assert "откройте бота «Касается меня»" in kwargs["text"]
    assert kwargs["attachments"][0].path == str(FIRST_START_IMAGE_PATH)
    assert db_session.get(ChatRow, -9001).welcome_mid == "group-mid"

    second = AddressRow(
        address_text="Москва, другой дом, д. 2",
        city="Москва",
        district="район Тестовый",
        street="другая улица",
        house="2",
        latitude=Decimal("55.7502000"),
        longitude=Decimal("37.6102000"),
    )
    db_session.add(second)
    db_session.flush()
    add_chat_address(db_session, -9001, second.id)
    asyncio.run(
        announce_connected_group(bot, -9001, address_text=second.address_text, additional=True)
    )
    bot.send_message.assert_awaited_once()
    bot.edit_message.assert_awaited_once()
    assert bot.edit_message.await_args.args[0] == "group-mid"
    edited = bot.edit_message.await_args.kwargs["text"]
    assert edited.startswith("Домовой чат по адресам:\n")
    assert f"• {first.address_text}" in edited and f"• {second.address_text}" in edited
    assert remove_chat_address(db_session, -9001, second.id)
    asyncio.run(announce_connected_group(bot, -9001))
    assert bot.edit_message.await_count == 2
    after_removal = bot.edit_message.await_args.kwargs["text"]
    assert first.address_text in after_removal and second.address_text not in after_removal


def test_group_setup_explains_welcome_after_binding() -> None:
    from chat_link.handlers.group import announce_group_address_setup

    bot = SimpleNamespace(
        get_me_from_chat=AsyncMock(
            return_value=SimpleNamespace(is_admin=False, is_owner=False, permissions=[])
        ),
        send_message=AsyncMock(),
    )
    asyncio.run(announce_group_address_setup(bot, -9001))
    message = bot.send_message.await_args.kwargs
    assert message["chat_id"] == -9001
    assert (
        "2. Перейдите в бота и завершите привязку к чату. "
        "После успешной привязки в чат придёт приветственное сообщение."
    ) in message["text"]
    assert "Проверить еще раз" not in message["text"]


def test_successful_binding_sends_new_welcome_instead_of_editing_old(db_session, monkeypatch):
    from contextlib import contextmanager

    import chat_link.handlers.group as group
    from user_chat.db import ChatRow

    @contextmanager
    def same_session():
        yield db_session

    monkeypatch.setattr(group, "session_scope", same_session)
    address = _address(db_session)
    create_chat(db_session, ChatCreate(chat_id=-9001, address_id=address.id, chat_type="chat"))
    db_session.get(ChatRow, -9001).welcome_mid = "hidden-old-mid"
    reply = SimpleNamespace(message=SimpleNamespace(body=SimpleNamespace(mid="new-mid")))
    bot = SimpleNamespace(
        me=SimpleNamespace(username="test_bot"),
        send_message=AsyncMock(return_value=reply),
        edit_message=AsyncMock(),
        delete_message=AsyncMock(),
    )

    asyncio.run(announce_connected_group(bot, -9001, new_message=True))

    bot.send_message.assert_awaited_once()
    bot.edit_message.assert_not_awaited()
    bot.delete_message.assert_awaited_once_with("hidden-old-mid")
    assert db_session.get(ChatRow, -9001).welcome_mid == "new-mid"
    welcome_text = bot.send_message.await_args.kwargs["text"]
    assert welcome_text.startswith(f"Домовой чат по адресу:\n• {address.address_text}")
    assert "откройте сервис по кнопке ниже:" in welcome_text
    button = bot.send_message.await_args.kwargs["attachments"][1].payload.buttons[0][0]
    assert button.text == "Присоединиться"
    assert "chat_-9001" in button.url


def test_group_welcome_falls_back_to_text_if_image_is_missing(db_session, monkeypatch):
    from contextlib import contextmanager

    import chat_link.handlers.group as group

    @contextmanager
    def same_session():
        yield db_session

    monkeypatch.setattr(group, "session_scope", same_session)
    address = _address(db_session)
    create_chat(db_session, ChatCreate(chat_id=-9001, address_id=address.id, chat_type="chat"))
    reply = SimpleNamespace(message=SimpleNamespace(body=SimpleNamespace(mid="new-mid")))
    bot = SimpleNamespace(
        me=SimpleNamespace(username="test_bot"),
        send_message=AsyncMock(side_effect=[FileNotFoundError("image"), reply]),
    )

    asyncio.run(announce_connected_group(bot, -9001, new_message=True))

    assert bot.send_message.await_count == 2
    first, second = bot.send_message.await_args_list
    assert len(first.kwargs["attachments"]) == 2  # Обложка и ссылка в личку.
    assert len(second.kwargs["attachments"]) == 1  # При повторе только ссылка.
    assert second.kwargs["attachments"][0].payload.buttons[0][0].text == "Присоединиться"


def test_group_address_lookup_shows_only_connected_group(db_session) -> None:
    address = _address(db_session)
    assert connected_group_address(db_session, -9028) is None
    create_chat(
        db_session,
        ChatCreate(chat_id=-9028, address_id=address.id, title="Соседи", chat_type="chat"),
    )
    assert connected_group_address(db_session, -9028) == address.address_text


def test_admin_adds_second_home_to_existing_courtyard_group(db_session) -> None:
    first = _address(db_session)
    second = AddressRow(
        address_text="Москва, район Тестовый, улица Соседская, д. 2",
        city="Москва",
        district="район Тестовый",
        street="улица Соседская",
        house="2",
        latitude=Decimal("55.7502000"),
        longitude=Decimal("37.6102000"),
    )
    db_session.add(second)
    admin = _user(db_session, 101)
    db_session.flush()
    bot = FakeBot(admins={admin.max_user_id}, bot_admin=True, bot_permissions=["read_all_messages"])
    for address in (first, second):
        result = asyncio.run(
            connect_added_group_to_address(
                bot, db_session, chat_id=-9025, admin_max_user_id=101, address_id=address.id
            )
        )
        assert result.connected

    assert get_chat(db_session, -9025).address_id == first.id
    assert [row.id for row in list_chat_addresses(db_session, -9025)] == [first.id, second.id]
    assert list_memberships_for_user(db_session, 101)[0].address_id == first.id
    assert first.address_text in connected_group_address(db_session, -9025)
    assert second.address_text in connected_group_address(db_session, -9025)
    again = asyncio.run(
        connect_added_group_to_address(
            bot, db_session, chat_id=-9025, admin_max_user_id=101, address_id=second.id
        )
    )
    assert again.connected
    assert len(list_chat_addresses(db_session, -9025)) == 2


def test_referral_prompts_personal_address_and_preserves_membership(db_session) -> None:
    address = _address(db_session)
    _user(db_session, 101)
    create_chat(db_session, ChatCreate(chat_id=-9050, address_id=address.id, title="Двор"))

    outcome = asyncio.run(
        bind_referral_member(FakeBot(members={101}), db_session, chat_id=-9050, max_user_id=101)
    )
    assert outcome.joined
    assert "Адрес чата сохранён" in outcome.message
    assert list_memberships_for_user(db_session, 101)[0].address_id == address.id


def test_referral_saves_every_chat_address_without_guessing_residence(db_session) -> None:
    from auth.db import UserRow
    from auth.handlers.managed_addresses import list_managed_addresses, remove_managed_address
    from user_chat.handlers import add_chat_address, remove_chat_address

    first = _address(db_session)
    second = AddressRow(
        address_text="Москва, Соседская, д. 2",
        latitude=Decimal("55.7500000"),
        longitude=Decimal("37.6100000"),
    )
    db_session.add(second)
    db_session.flush()
    user = _user(db_session, 212)
    create_chat(db_session, ChatCreate(chat_id=-9110, address_id=first.id, title="Наш двор"))
    add_chat_address(db_session, -9110, second.id)

    outside = asyncio.run(
        bind_referral_member(FakeBot(), db_session, chat_id=-9110, max_user_id=212)
    )
    assert not outside.joined
    assert list_managed_addresses(db_session, 212) == []

    inside = asyncio.run(
        bind_referral_member(FakeBot(members={212}), db_session, chat_id=-9110, max_user_id=212)
    )
    assert inside.joined
    assert "Все 2 адреса" in inside.message
    assert {item.id for item in list_managed_addresses(db_session, 212)} == {
        first.id,
        second.id,
    }
    assert db_session.get(UserRow, user.id).address_id is None
    assert list_memberships_for_user(db_session, 212) == []

    # Повторный переход ничего не дублирует.
    asyncio.run(
        bind_referral_member(FakeBot(members={212}), db_session, chat_id=-9110, max_user_id=212)
    )
    assert len(list_managed_addresses(db_session, 212)) == 2

    # Личное удаление не отвязывает дом от группы.
    assert remove_managed_address(db_session, max_user_id=212, address_id=first.id)
    assert {item.id for item in list_managed_addresses(db_session, 212)} == {second.id}
    assert {address.id for address in list_chat_addresses(db_session, -9110)} == {
        first.id,
        second.id,
    }
    # Отвязка администратором убирает этот дом из списка всех жителей.
    assert remove_chat_address(db_session, -9110, second.id)
    assert list_managed_addresses(db_session, 212) == []
