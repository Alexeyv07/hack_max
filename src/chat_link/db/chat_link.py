"""Заявка/токен подключения соседского чата (KAN-7)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from project.database import Base


class ChatLinkRow(Base):
    __tablename__ = "chat_links"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_bot', 'pending_admin', 'ready', 'cancelled')",
            name="ck_chat_links_status",
        ),
    )

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    address_id: Mapped[int] = mapped_column(
        ForeignKey("addresses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chat_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("chats.chat_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
