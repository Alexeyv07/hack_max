FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_OFFLINE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src ./src
COPY conf ./conf
COPY alembic.ini .
COPY alembic ./alembic
COPY scripts ./scripts
COPY ml/classify/rules.yaml ./ml/classify/rules.yaml
# Веса classify (ONNX + tokenizer + meta). При отсутствии файла на хосте
# build упадёт — сначала: python ml/classify/train_torch.py
COPY ml/classify/artifacts ./ml/classify/artifacts

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[ml-runtime]"

CMD ["python", "/app/scripts/bot_entrypoint.py"]
