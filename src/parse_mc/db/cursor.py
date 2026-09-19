"""ORM: состояние парсера УК по каждому источнику."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from project.database import Base


class McParserCursorRow(Base):
    """Watermark / resume-курсор одного источника УК/ЖЭК."""

    __tablename__ = "mc_parser_cursors"

    source_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    backfill_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    oldest_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    newest_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    listing_cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"McParserCursorRow(source_key={self.source_key!r}, "
            f"backfill_complete={self.backfill_complete!r})"
        )
