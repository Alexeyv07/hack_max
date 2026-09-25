"""Единое оформление сообщений MAX, без повторной отправки приветственной обложки.

Картинки кэшируются через upload token: иначе каждый send/edit заново грузит
~400KB на CDN MAX и бот ощущается «тормозным».
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from maxapi.types import InputMedia
from maxapi.types.attachments.upload import AttachmentUpload

# Корень репозитория: src/project/bot_media.py → parents[2]
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
FIRST_START_IMAGE_PATH = ASSETS_DIR / "first_start.jpg"
OTHER_MESSAGES_IMAGE_PATH = ASSETS_DIR / "other_messages.jpg"
HOME_IMAGE_PATH = ASSETS_DIR / "home.jpg"

_CACHE_ATTR = "_brand_image_cache"


def first_start_image(bot: Any | None = None) -> InputMedia | AttachmentUpload:
    return _cached_or_path(bot, "first_start", FIRST_START_IMAGE_PATH)


def home_image(bot: Any | None = None) -> InputMedia | AttachmentUpload:
    return _cached_or_path(bot, "home", HOME_IMAGE_PATH)


def other_messages_image(bot: Any | None = None) -> InputMedia | AttachmentUpload:
    return _cached_or_path(bot, "other", OTHER_MESSAGES_IMAGE_PATH)


def _cached_or_path(bot: Any | None, key: str, path: Path) -> InputMedia | AttachmentUpload:
    cache = getattr(bot, _CACHE_ATTR, None) if bot is not None else None
    if isinstance(cache, dict) and key in cache:
        return cache[key]
    return InputMedia(str(path), type="image")


def _attachment_kind(item: Any) -> str:
    raw = getattr(item, "type", "")
    value = getattr(raw, "value", raw)
    return str(value).lower()


def _has_image(attachments: Any) -> bool:
    return any(_attachment_kind(item) in {"image", "photo"} for item in (attachments or []))


def _is_priority_notify_text(text: str | None) -> bool:
    """Личные priority-пуши начинаются маркером важности — без брендовой обложки."""
    if not text:
        return False
    stripped = text.lstrip()
    return stripped.startswith(("🔴", "🟠"))


def _other_image(bot: Any, attachments: Any, text: str | None) -> list[Any] | None:
    """Оставить тематическое изображение, если оно уже задано явно."""
    if text is None or text.startswith("<b>Главная</b>") or _is_priority_notify_text(text):
        return attachments
    if _has_image(attachments):
        return attachments
    return [other_messages_image(bot), *(attachments or [])]


async def warm_bot_images(bot: Any) -> None:
    """Один раз загрузить обложки в MAX и дальше слать только token."""
    if getattr(bot, _CACHE_ATTR, None):
        return
    upload = getattr(bot, "upload_media", None)
    if not callable(upload):
        return
    cache: dict[str, AttachmentUpload] = {}
    for key, path in (
        ("first_start", FIRST_START_IMAGE_PATH),
        ("home", HOME_IMAGE_PATH),
        ("other", OTHER_MESSAGES_IMAGE_PATH),
    ):
        if not path.is_file():
            continue
        try:
            cache[key] = await upload(InputMedia(str(path), type="image"))
        except Exception:
            # Без кэша остаёмся на InputMedia — медленнее, но бот жив.
            from project.logging_setup import get_logger

            get_logger(__name__).exception("Не удалось прогреть обложку %s", path.name)
    if cache:
        setattr(bot, _CACHE_ATTR, cache)


def install_bot_images(bot: Any) -> None:
    """Оформить новые исходящие сообщения брендовой обложкой.

    Не трогаем edit/callback: иначе каждый шаг picker-а снова upload-ит JPG.
    Передайте brand_image=False, чтобы не вставлять other_messages.jpg.
    """
    if getattr(bot, "_brand_images_installed", False):
        return
    original_send_message = bot.send_message

    async def send_message(*args: Any, **kwargs: Any) -> Any:
        # По умолчанию без обложки: upload на каждый ответ делает бота «тормозным».
        # Явно brand_image=True — только для экранов, где картинка нужна.
        brand = kwargs.pop("brand_image", False)
        if brand and "text" in kwargs:
            kwargs["attachments"] = _other_image(bot, kwargs.get("attachments"), kwargs["text"])
        return await original_send_message(*args, **kwargs)

    bot.send_message = send_message
    bot._brand_images_installed = True
