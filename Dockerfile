FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src ./src
COPY conf ./conf
COPY alembic.ini .
COPY alembic ./alembic
COPY scripts/bot_entrypoint.py /app/scripts/bot_entrypoint.py

RUN pip install --no-cache-dir .

CMD ["python", "/app/scripts/bot_entrypoint.py"]
