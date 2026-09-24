"""Единое оформление сообщений MAX, без повторной отправки приветственной обложки."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from maxapi.types import InputMedia

ASSETS_DIR = Path(__file__).resolve().parents[1] / "auth" / "assets"
FIRST_START_IMAGE_PATH = ASSETS_DIR / "first_start.jpg"
OTHER_MESSAGES_IMAGE_PATH = ASSETS_DIR / "other_messages.jpg"


def first_start_image() -> InputMedia:
    return InputMedia(str(FIRST_START_IMAGE_PATH), type="image")


def _has_image(attachments: Any) -> bool:
    return any(str(getattr(item, "type", "")).lower() == "image" for item in (attachments or []))


def _other_image(attachments: Any, text: str | None) -> list[Any] | None:
    """Оставить тематическое изображение, если оно уже задано явно."""
    if text is None or text.startswith("<b>Главная</b>"):
        return attachments
    if _has_image(attachments):
        return attachments
    return [InputMedia(str(OTHER_MESSAGES_IMAGE_PATH), type="image"), *(attachments or [])]


def install_bot_images(bot: Any) -> None:
    """Оформить все исходящие сообщения, включая ответы на inline-callback.

    Не меняем сами callback-уведомления (ack), если там нет сообщения.
    Повторный вызов не добавляет обёртки повторно.
    """
    if getattr(bot, "_brand_images_installed", False):
        return
    original_send_message = bot.send_message
    original_edit_message = bot.edit_message
    original_send_callback = bot.send_callback

    async def send_message(*args: Any, **kwargs: Any) -> Any:
        if "text" in kwargs:
            kwargs["attachments"] = _other_image(kwargs.get("attachments"), kwargs["text"])
        return await original_send_message(*args, **kwargs)

    async def edit_message(*args: Any, **kwargs: Any) -> Any:
        if "text" in kwargs:
            kwargs["attachments"] = _other_image(kwargs.get("attachments"), kwargs["text"])
        return await original_edit_message(*args, **kwargs)

    async def send_callback(*args: Any, **kwargs: Any) -> Any:
        message = kwargs.get("message")
        if message is not None and message.text is not None:
            attachments = _other_image(message.attachments, message.text)
            kwargs["message"] = message.model_copy(update={"attachments": attachments})
        return await original_send_callback(*args, **kwargs)

    bot.send_message = send_message
    bot.edit_message = edit_message
    bot.send_callback = send_callback
    bot._brand_images_installed = True
