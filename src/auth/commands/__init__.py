"""Привязка команд Max к модулю авторизации."""

from auth.commands.bot_commands import publish_bot_commands
from auth.commands.start import register_auth_commands

__all__ = ["publish_bot_commands", "register_auth_commands"]
