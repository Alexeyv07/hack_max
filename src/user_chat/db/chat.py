"""Чаты соседей и связь зарегистрированных пользователей с чатами."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, Table
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
)


class ChatRow(Base):
    """Один MAX-чат; несколько чатов могут ссылаться на один адрес."""

    __tablename__ = "chats"

    # Это внешний MAX id, включая отрицательные значения, а не локальный счётчик.
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    invite_link: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # NULL — legacy-запись до реальной group integration KAN-7. Такие записи
    # нельзя считать домовыми группами: раньше сюда временно писали DIALOG chat_id.
    chat_type: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    address_id: Mapped[int] = mapped_column(
        ForeignKey("addresses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    address: Mapped[AddressRow] = relationship("AddressRow")
    users: Mapped[list[UserRow]] = relationship(
        "UserRow", secondary=users_chat, passive_deletes=True
    )
