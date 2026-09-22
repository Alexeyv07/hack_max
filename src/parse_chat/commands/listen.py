"""Тонкая обёртка Max-событий → parse_chat handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from parse_chat.handlers.process import process_chat_event
from project.logging_setup import get_logger

logger = get_logger(__name__)


def register_parse_chat_commands(dp: Any, bot: Any) -> None:
    """Слушать message_created: одно сообщение → полный flow, без очереди."""

    @dp.message_created()
    async def on_chat_message(event: Any) -> None:
        try:
            # to_thread: ML/SQL не блокируют loop; Dispatcher всё равно ждёт
            # завершения handle до следующего update (use_create_task=False).
            await asyncio.to_thread(process_chat_event, event)
        except Exception:
            logger.exception("parse_chat: ошибка обработки message_created")
