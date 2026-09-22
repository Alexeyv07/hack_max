"""Буфер: фото без текста ждёт следующее сообщение того же автора."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from parse_chat.models.message import RawChatMessage


@dataclass(frozen=True, slots=True)
class PendingPhoto:
    url: str
    message_id: str
    stored_at: float


class PendingPhotoBuffer:
    """In-memory (chat_id, user_id) → последнее фото без подписи."""

    def __init__(self) -> None:
        self._items: dict[tuple[int, int], PendingPhoto] = {}

    def put(
        self,
        *,
        chat_id: int,
        user_id: int,
        url: str,
        message_id: str,
        now: float | None = None,
    ) -> None:
        self._items[(chat_id, user_id)] = PendingPhoto(
            url=url,
            message_id=message_id,
            stored_at=now if now is not None else time.monotonic(),
        )

    def take(
        self,
        *,
        chat_id: int,
        user_id: int,
        window_seconds: float,
        now: float | None = None,
    ) -> PendingPhoto | None:
        key = (chat_id, user_id)
        item = self._items.get(key)
        if item is None:
            return None
        ts = now if now is not None else time.monotonic()
        if window_seconds > 0 and (ts - item.stored_at) > window_seconds:
            self._items.pop(key, None)
            return None
        self._items.pop(key, None)
        return item

    def clear(self) -> None:
        self._items.clear()


_PENDING = PendingPhotoBuffer()


def get_pending_photo_buffer() -> PendingPhotoBuffer:
    return _PENDING


def apply_pending_photo(
    message: RawChatMessage,
    *,
    buffer: PendingPhotoBuffer | None = None,
    window_seconds: float = 600.0,
    now: float | None = None,
) -> tuple[RawChatMessage, str]:
    """
    Связать фото с текстом.

    Returns:
      (message, action) где action:
        - ``hold_photo`` — только фото, ждём текст того же автора (не persist)
        - ``attached`` — взяли pending-фото к тексту
        - ``passthrough`` — как есть (текст без фото / фото+текст / …)
    """
    buf = buffer if buffer is not None else _PENDING
    text = (message.text or "").strip()
    has_image = bool(message.image_url)
    user_id = message.sender_user_id

    # Фото без текста → отложить до следующего сообщения автора.
    if has_image and not text and user_id is not None:
        buf.put(
            chat_id=message.chat_id,
            user_id=user_id,
            url=message.image_url or "",
            message_id=message.message_id,
            now=now,
        )
        return message, "hold_photo"

    # Текст без своего фото → подтянуть отложенное фото того же автора.
    if text and not has_image and user_id is not None:
        pending = buf.take(
            chat_id=message.chat_id,
            user_id=user_id,
            window_seconds=window_seconds,
            now=now,
        )
        if pending is not None and pending.url:
            return replace(message, image_url=pending.url), "attached"

    # Фото+текст в одном сообщении — сбрасываем старый pending этого автора.
    if has_image and text and user_id is not None:
        buf.take(
            chat_id=message.chat_id,
            user_id=user_id,
            window_seconds=window_seconds,
            now=now,
        )

    return message, "passthrough"
