"""Извлечение текста / картинок из Max Message."""

from __future__ import annotations

from typing import Any


def _att_type(attachment: Any) -> str:
    raw = getattr(attachment, "type", None)
    if raw is None and isinstance(attachment, dict):
        raw = attachment.get("type")
    value = getattr(raw, "value", raw)
    return str(value or "").lower()


def _att_payload(attachment: Any) -> Any:
    payload = getattr(attachment, "payload", None)
    if payload is None and isinstance(attachment, dict):
        payload = attachment.get("payload")
    return payload


def extract_image_url(attachments: Any) -> str | None:
    """
    URL первой картинки из attachments (Image / photo payload.url).

    Стикеры игнорируем — для ленты нужна фотография события.
    """
    if not attachments:
        return None
    for attachment in attachments:
        kind = _att_type(attachment)
        if kind not in {"image", "photo"}:
            continue
        payload = _att_payload(attachment)
        if payload is None:
            continue
        url = getattr(payload, "url", None)
        if url is None and isinstance(payload, dict):
            url = payload.get("url")
        if isinstance(url, str) and url.strip().startswith(("http://", "https://")):
            return url.strip()
    return None


def has_non_image_attachments(attachments: Any) -> bool:
    """Есть вложения, но ни одно не image (стикер / файл / …)."""
    if not attachments:
        return False
    saw_any = False
    for attachment in attachments:
        saw_any = True
        if _att_type(attachment) in {"image", "photo"}:
            return False
    return saw_any
