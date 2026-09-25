"""Сборка FastAPI-приложения."""

from __future__ import annotations

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware

from chat_link.api import router as chat_link_router
from events.api.routes import router as events_router
from events.api.schemas import HealthResponse
from project.config import get_settings

_OPENAPI_DESCRIPTION = """
## «Умный город» — HTTP API для Max WebApp

Read-only API мини-приложения в мессенджере **Max**: лента событий (TikTok-карточки),
карта и онбординг адреса / домового чата.

### Аутентификация

Почти все ручки требуют заголовок:

| Заголовок | Тип | Описание |
|-----------|-----|----------|
| `X-Max-User-Id` | integer | ID пользователя Max (`initDataUnsafe.user.id` из Bridge). Локально можно подставить тестовый id = `159064979`. |

Без заголовка → **401** `{ "detail": "Нужен заголовок X-Max-User-Id" }`.

> Запись событий (парсеры, бот, dedup) идёт **только in-process** через handlers —
> HTTP не создаёт и не обновляет `events`.

### Модули

| Тег | Префикс | Назначение |
|-----|---------|------------|
| **events** | `/events` | Лента nearby/city и точки карты |
| **chat-link** | `/chat-link` | Поиск адреса, выбор дома, привязка домового чата |
| **system** | `/health` | Liveness для оркестраторов / compose |

### CORS

Разрешены `localhost` / `127.0.0.1` (Vite) и regex `https://.*\\.cloudpub\\.ru`
(публичный HTTPS туннель для Max).

### Быстрый старт (curl)

```bash
curl -s "http://localhost:8000/events/feed?scope=nearby&limit=5" \\
  -H "X-Max-User-Id: 159064979"

curl -s "http://localhost:8000/events/map?limit=100" \\
  -H "X-Max-User-Id: 159064979"
```

Интерактивная песочница: **/docs** (Swagger UI) · **/redoc** (ReDoc).
""".strip()

_OPENAPI_TAGS = [
    {
        "name": "Events",
        "description": (
            "Чтение финальных событий из таблицы `events` для webapp. "
            "Лента ранжируется по весу; карта отдаёт маркеры с категорией иконки. "
            "**Только GET.**"
        ),
    },
    {
        "name": "ChatLink",
        "description": (
            "Онбординг адреса жителя и привязка MAX group chat к дому: "
            "поиск по тексту / индексу / карте, выбор адреса, проверка членства через бота."
        ),
    },
    {
        "name": "System",
        "description": "Служебные эндпоинты процесса (healthcheck).",
    },
]


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app.name} · Events & Chat-link API",
        version="0.1.0",
        debug=settings.app.debug,
        description=_OPENAPI_DESCRIPTION,
        openapi_tags=_OPENAPI_TAGS,
        contact={
            "name": "Documentations",
            "url": settings.docs.url,
        },
        license_info={
            "name": "Project source",
            "url": settings.docs.github_url,
        },
        swagger_ui_parameters={
            "docExpansion": "list",
            "defaultModelsExpandDepth": 2,
            "displayRequestDuration": True,
            "filter": True,
            "tryItOutEnabled": True,
            "persistAuthorization": True,
        },
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.api.cors_origins),
        allow_origin_regex=r"https://.*\.cloudpub\.ru",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(events_router)
    app.include_router(chat_link_router)

    @app.get(
        "/health",
        tags=["System"],
        summary="Liveness",
        response_model=HealthResponse,
        response_description="Процесс API жив",
        responses={
            status.HTTP_200_OK: {
                "description": "OK — uvicorn/FastAPI отвечает в этом процессе.",
                "model": HealthResponse,
            },
        },
    )
    def health() -> HealthResponse:
        """
        Простейший healthcheck без обращения к БД и Max API.

        Используется docker/compose и локальной отладкой (`GET /health`).
        Не требует `X-Max-User-Id`.
        """
        return HealthResponse(status="ok")

    return app
