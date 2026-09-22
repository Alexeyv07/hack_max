"""Тонкая обёртка Max-событий → parse_chat handlers (низкая latency)."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from parse_chat.handlers.process import process_chat_event
from project.logging_setup import get_logger

logger = get_logger(__name__)

# Отдельный пул: news/mc не должны занимать default to_thread и тормозить чат.
_CHAT_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="parse_chat")
_CHAT_SEM = asyncio.Semaphore(2)
_BACKGROUND: set[asyncio.Task[None]] = set()


def register_parse_chat_commands(dp: Any, bot: Any) -> None:
    """Слушать message_created: не блокировать polling — запись в фоне."""

    @dp.message_created()
    async def on_chat_message(event: Any) -> None:
        # Сразу возвращаемся в Dispatcher → следующий get_updates.
        # Persist/ML — в dedicated thread pool (не делим с news/mc to_thread).
        task = asyncio.create_task(_process_chat_bg(event), name="parse_chat")
        _BACKGROUND.add(task)
        task.add_done_callback(_BACKGROUND.discard)


async def _process_chat_bg(event: Any) -> None:
    try:
        async with _CHAT_SEM:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(_CHAT_EXECUTOR, process_chat_event, event)
    except Exception:
        logger.exception("parse_chat: ошибка фоновой обработки message_created")
