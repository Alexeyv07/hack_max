"""Общая инфраструктура приложения: конфиг, логирование, БД."""

from project.config import get_settings
from project.logging_setup import setup_logging

__all__ = ["get_settings", "setup_logging"]
