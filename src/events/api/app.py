"""Сборка FastAPI-приложения."""

from __future__ import annotations

from fastapi import FastAPI

from events.api.routes import router as events_router
from project.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app.name} events API",
        version="0.1.0",
        debug=settings.app.debug,
    )
    app.include_router(events_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
