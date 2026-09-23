"""Обработка Max message_created → filter → persist."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from parse_chat.handlers.filter import FilterConfig, filter_message
from parse_chat.handlers.ingest import load_active_chat_row, persist_chat_message
from parse_chat.handlers.media import extract_image_url, has_non_image_attachments
from parse_chat.handlers.pending_photo import apply_pending_photo
from parse_chat.models.message import RawChatMessage
from project.config import get_settings
from project.database import session_scope
from project.logging_setup import get_logger
from project.max_events import extract_chat_id, extract_sender

logger = get_logger(__name__)


def _filter_config_from_settings() -> FilterConfig:
    cfg = get_settings().chat_parser
    greetings = tuple(cfg.greeting_only) if cfg.greeting_only else FilterConfig().greeting_only
    return FilterConfig(
        min_chars=cfg.min_chars,
        flood_window_seconds=cfg.flood_window_seconds,
        flood_max_repeats=cfg.flood_max_repeats,
        greeting_only=greetings,
    )


def _message_text(message: Any) -> str:
    body = getattr(message, "body", None)
    text = getattr(body, "text", None) if body is not None else None
    return str(text) if text else ""


def _message_id(message: Any) -> str | None:
    body = getattr(message, "body", None)
    mid = getattr(body, "mid", None) if body is not None else None
    return str(mid) if mid else None


def _attachments(message: Any) -> Any:
    body = getattr(message, "body", None)
    return getattr(body, "attachments", None) if body is not None else None


def _published_at(message: Any) -> datetime | None:
    ts = getattr(message, "timestamp", None)
    if ts is None:
        return None
    try:
        value = int(ts)
        if value > 10_000_000_000:
            value //= 1000
        return datetime.fromtimestamp(value, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _chat_type(message: Any) -> str | None:
    recipient = getattr(message, "recipient", None)
    chat_type = getattr(recipient, "chat_type", None) if recipient is not None else None
    if chat_type is None:
        return None
    return str(getattr(chat_type, "value", chat_type)).lower()


def _message_source_url(message: Any, mid: str) -> str | None:
    """Прямая ссылка на сообщение в MAX (url из API или сборка из mid)."""
    url = getattr(message, "url", None) or getattr(message, "url_api", None)
    if isinstance(url, str) and url.strip().startswith(("http://", "https://")):
        return url.strip()
    try:
        from maxapi.utils.message_link import build_message_link

        return build_message_link(mid)
    except Exception:
        return None


def extract_raw_chat_message(event: Any) -> RawChatMessage | None:
    """Вытащить RawChatMessage из MessageCreated; None если нечего парсить."""
    message = getattr(event, "message", None)
    if message is None:
        return None

    chat_type = _chat_type(message)
    if chat_type is not None and chat_type != "chat":
        return None

    chat_id = extract_chat_id(event)
    if chat_id is None:
        return None

    mid = _message_id(message)
    if not mid:
        return None

    sender = extract_sender(event)
    sender_id = getattr(sender, "user_id", None) if sender is not None else None
    is_bot = bool(getattr(sender, "is_bot", False)) if sender is not None else False

    attachments = _attachments(message)
    image_url = extract_image_url(attachments)
    has_att = bool(attachments)
    sticker_like = (not image_url) and has_non_image_attachments(attachments)

    return RawChatMessage(
        chat_id=int(chat_id),
        message_id=mid,
        text=_message_text(message),
        sender_user_id=int(sender_id) if sender_id is not None else None,
        sender_is_bot=is_bot,
        published_at=_published_at(message),
        has_attachments=has_att or sticker_like,
        image_url=image_url,
        source_url=_message_source_url(message, mid),
    )


def process_chat_event(event: Any) -> bool:
    """
    Синхронный inline-путь на одно сообщение:

      photo-hold / attach → filter → normalize → ml_dedup → commit

    Нет фото ≠ drop. Фото без текста ждёт следующее сообщение того же автора.
    """
    settings = get_settings()
    if not settings.runtime.enable_chat_parser or not settings.chat_parser.enabled:
        return False

    raw = extract_raw_chat_message(event)
    if raw is None:
        return False

    window = float(getattr(settings.chat_parser, "photo_attach_window_seconds", 600))
    raw, photo_action = apply_pending_photo(raw, window_seconds=window)
    if photo_action == "hold_photo":
        logger.debug(
            "parse_chat hold photo chat=%s mid=%s user=%s — ждём текст",
            raw.chat_id,
            raw.message_id,
            raw.sender_user_id,
        )
        return False

    with session_scope() as session:
        chat = load_active_chat_row(session, raw.chat_id)
        if chat is None:
            return False

        verdict = filter_message(raw, _filter_config_from_settings())
        if not verdict.accepted:
            logger.debug(
                "parse_chat skip chat=%s mid=%s reason=%s",
                raw.chat_id,
                raw.message_id,
                verdict.reason,
            )
            return False

        event_row = persist_chat_message(session, raw, chat=chat)
        if event_row is None:
            return False
        logger.info(
            "parse_chat inline ok event_id=%s chat=%s mid=%s importance=%s "
            "signal=%s image=%s photo_action=%s",
            event_row.id,
            raw.chat_id,
            raw.message_id,
            event_row.importance,
            verdict.signal,
            bool(event_row.image_url),
            photo_action,
        )
        return True
