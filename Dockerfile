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
COPY scripts ./scripts

# ML runtime artifacts (train → artifacts; без ONNX — soft fallback в коде)
COPY ml/classify/rules.yaml ./ml/classify/rules.yaml
COPY ml/classify/artifacts ./ml/classify/artifacts
COPY ml/time/artifacts ./ml/time/artifacts
COPY ml/dedup/artifacts ./ml/dedup/artifacts
COPY ml/dedup/config.yaml ./ml/dedup/config.yaml

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[ml-runtime]" \
    && python -m spacy download ru_core_news_md

CMD ["python", "/app/scripts/bot_entrypoint.py"]
