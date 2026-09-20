from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

from maxapi.enums import ChatType

from address.db import AddressRow
from auth.handlers.authorize import authorize_user
from auth.models.user import MaxUserPayload
from chat_link.handlers import (
    bind_referral_member,
    bot_can_read_group,
    claim_admin_request,
    connect_added_group,
    connect_group_chat,
    create_request,
    existing_group_chats,
    join_existing_chat,
    pending_for_actor,
)
from chat_link.models import ChatLinkStatus
from user_chat.handlers import create_chat, get_chat, list_chat_members
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
    assert outcome.invite_link == "https://max.ru/join/existing"
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
