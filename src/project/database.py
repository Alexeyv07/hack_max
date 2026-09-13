"""Движок SQLAlchemy, фабрика сессий и declarative base для PostgreSQL."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from project.config import get_settings
from project.logging_setup import get_logger

logger = get_logger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""


def get_engine(*, force_new: bool = False) -> Engine:
    """Создать (или переиспользовать) движок SQLAlchemy из настроек."""
    global _engine, _SessionLocal

    if _engine is not None and not force_new:
        return _engine

    settings = get_settings()
    db = settings.database
    url = db.sqlalchemy_url()

    # Не светим пароль в логах
    safe_url = url.split("@")[-1] if "@" in url else url
    logger.info("Создаём DB engine → postgresql://***@%s", safe_url)

    _engine = create_engine(
        url,
        echo=db.echo,
        pool_size=db.pool_size,
        max_overflow=db.max_overflow,
        pool_pre_ping=True,
        future=True,
    )
    _SessionLocal = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Транзакционная область: commit при успехе, rollback при ошибке."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Сессия БД откачена из-за ошибки")
        raise
    finally:
        session.close()


def check_connection() -> bool:
    """Проверить доступность PostgreSQL; True, если соединение живо."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("Подключение к PostgreSQL OK")
    return True


def dispose_engine() -> None:
    """Закрыть движок и сбросить фабрику сессий (тесты / shutdown)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
