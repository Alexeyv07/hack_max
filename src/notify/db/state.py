"""Персистентное состояние воркеров уведомлений."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from project.database import Base


class NotifyDeliveryRow(Base):
    """Личное уведомление по событию для конкретного пользователя."""

    __tablename__ = "notify_deliveries"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_notify_delivery_user_event"),
        Index("ix_notify_deliveries_acked_at", "acked_at"),
        Index("ix_notify_deliveries_last_sent_at", "last_sent_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NotifyDigestRow(Base):
    """Последняя обработанная дата дайджеста и время фактической отправки."""

    __tablename__ = "notify_digests"

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chats.chat_id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    last_digest_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ID последней обработанной записи устраняет пропуски при одинаковых timestamp.
    last_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class NotifyCursorRow(Base):
    """Курсор событий для первичных личных уведомлений."""

    __tablename__ = "notify_cursors"

    name: Mapped[str] = mapped_column(primary_key=True)
    last_event_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
