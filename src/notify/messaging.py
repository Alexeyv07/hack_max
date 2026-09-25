"""Общие хелперы отправки/удаления сообщений notify в MAX."""

from __future__ import annotations

from typing import Any

from project.logging_setup import get_logger

logger = get_logger(__name__)


def sent_mid(result: Any) -> str | None:
    message = getattr(result, "message", None)
    body = getattr(message, "body", None)
    mid = getattr(body, "mid", None)
    return str(mid) if mid else None


async def delete_message_quiet(bot: Any, message_mid: str | None) -> None:
    """Удалить сообщение в MAX; ошибки глотаем (сообщение могли стереть вручную)."""
    if not message_mid:
        return
    delete = getattr(bot, "delete_message", None)
    if not callable(delete):
        return
    try:
        await delete(message_mid)
    except Exception:
        logger.debug("Не удалось удалить сообщение mid=%s", message_mid, exc_info=True)
