"""ORM-модель: таблица events."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from project.database import Base

if TYPE_CHECKING:
    from address.db.address import AddressRow


class EventRow(Base):
    """Финальное событие для ленты и уведомлений."""

    __tablename__ = "events"
    __table_args__ = (
        Index(
            "uq_events_source_msg",
            "source",
            "source_msg_id",
            unique=True,
            postgresql_where=text("source_msg_id IS NOT NULL"),
            sqlite_where=text("source_msg_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    address_id: Mapped[int | None] = mapped_column(
        ForeignKey("addresses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    address: Mapped[AddressRow | None] = relationship("AddressRow")
    # Точность гео: city | street | home (null — без привязки).
    geo_by: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, index=True)
    source_msg_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    disaster_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    image_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
        doc="Главная фото события; null → фронт показывает карту с меткой",
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="Время публикации у источника (для timeliness веса)",
    )
    active_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="Начало действия события (отключение, ремонт, ЧС…)",
    )
    active_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="Конец действия; null = ещё актуально / неизвестно",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"EventRow(id={self.id!r}, title={self.title!r}, importance={self.importance!r})"
