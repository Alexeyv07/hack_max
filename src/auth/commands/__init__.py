"""Привязка команд Max к модулю авторизации."""

from auth.commands.start import register_auth_commands

__all__ = ["register_auth_commands"]
