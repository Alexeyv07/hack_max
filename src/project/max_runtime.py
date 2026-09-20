from __future__ import annotations

from typing import Any

_bot: Any | None = None


def set_max_bot(bot: Any | None) -> None:
    global _bot
    _bot = bot


def get_max_bot() -> Any | None:
    return _bot
