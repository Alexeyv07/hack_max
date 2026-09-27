"""Чаты соседей и связь зарегистрированных пользователей с чатами."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Column, ForeignKey, ForeignKeyConstraint, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from project.database import Base

if TYPE_CHECKING:
    from address.db.address import AddressRow
    from auth.db.user import UserRow


users_chat = Table(
    "users_chat",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "chat_id",
        BigInteger,
        ForeignKey("chats.chat_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
    Column("address_id", Integer, ForeignKey("addresses.id", ondelete="RESTRICT"), nullable=True),
)

chat_addresses = Table(
    "chat_addresses",
    Base.metadata,
    Column(
        "chat_id", BigInteger, ForeignKey("chats.chat_id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "address_id",
        Integer,
        ForeignKey("addresses.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    ),
)


# Адреса, сохранённые конкретным жителем по подтверждённой ссылке чата.
# Не подменяем ими единственный выбранный дом в users_chat.address_id.
user_chat_addresses = Table(
    "user_chat_addresses",
    Base.metadata,
    Column("user_id", Integer, primary_key=True),
    Column("chat_id", BigInteger, primary_key=True),
    Column("address_id", Integer, primary_key=True),
    ForeignKeyConstraint(
        ["user_id", "chat_id"],
        ["users_chat.user_id", "users_chat.chat_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["chat_id", "address_id"],
        ["chat_addresses.chat_id", "chat_addresses.address_id"],
        ondelete="CASCADE",
    ),
)


class ChatRow(Base):
    """Один MAX-чат; address_id — первый адрес (совместимость со старым парсером)."""

    __tablename__ = "chats"

    # Это внешний MAX id, включая отрицательные значения, а не локальный счётчик.
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    invite_link: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    welcome_mid: Mapped[str | None] = mapped_column(String, nullable=True)
    # NULL — legacy-запись до реальной group integration KAN-7. Такие записи
    # нельзя считать домовыми группами: раньше сюда временно писали DIALOG chat_id.
    chat_type: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    address_id: Mapped[int] = mapped_column(
        ForeignKey("addresses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    address: Mapped[AddressRow] = relationship("AddressRow")
    addresses: Mapped[list[AddressRow]] = relationship("AddressRow", secondary=chat_addresses)
    users: Mapped[list[UserRow]] = relationship(
        "UserRow", secondary=users_chat, passive_deletes=True
    )
