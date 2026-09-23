"""Совместимые импорты общих HTTP-зависимостей WebApp."""

from project.api_deps import DbSession, get_db_session, get_max_user_id

__all__ = ["DbSession", "get_db_session", "get_max_user_id"]
