"""Текстовые сообщения подключённых домовых чатов для ежедневного #итого."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from project.database import Base


class NotifyChatMessageRow(Base):
    """Отдельная история переписки: события из parse_chat не подходят для дайджеста."""

    __tablename__ = "notify_chat_messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "message_id", name="uq_notify_chat_message_chat_mid"),
        Index("ix_notify_chat_messages_chat_id_id", "chat_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chats.chat_id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
