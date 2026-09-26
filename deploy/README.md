# Deploy — prod образы (GHCR) + ONNX

Релизный стек: три образа в GHCR, локальный/серверный запуск через
`docker-compose.prod.yaml`. Секреты — только в корневом `.env`.

| Образ | Что внутри |
|-------|------------|
| `ghcr.io/alexeyv07/hack_max-postgres` | Postgres 16 + migrations + seed CSV |
| `ghcr.io/alexeyv07/hack_max-bot` | Python bot/API/parsers + ONNX |
| `ghcr.io/alexeyv07/hack_max-webapp` | Static SvelteKit + nginx (`/api` → bot) |

Сборка образов — GitHub Actions при пуше тега `v*` (см. `.github/workflows/release-images.yaml`).

Dev-стек (`docker-compose.yaml` в корне) не трогаем.

---

## Куда загрузить ONNX

ONNX **не коммитить** в git (~350 MB, в `.gitignore`). Хранилище — **GitHub Release
с тегом `models`** в этом репозитории.

Нужны три файла с **фиксированными именами**:

| Asset в Release `models` | Локальный путь (до загрузки) |
|--------------------------|------------------------------|
| `importance_model.onnx` | `ml/classify/artifacts/importance_model.onnx` |
| `time_window_model.onnx` | `ml/time/artifacts/time_window_model.onnx` |
| `embed_model.onnx` | `ml/dedup/artifacts/embed_model.onnx` |

Tokenizer / `*.meta.json` уже в git — в bot-образ попадут сами.

### Первый раз

```bash
# из корня репо, файлы уже лежат в ml/*/artifacts/
gh release create models --title "ML ONNX models" --notes "Runtime ONNX for bot image" \
  ml/classify/artifacts/importance_model.onnx \
  ml/time/artifacts/time_window_model.onnx \
  ml/dedup/artifacts/embed_model.onnx
```

Или через UI: **Releases → Draft a new release → tag `models` → Upload assets → Publish**.

### Обновить веса (без нового тега приложения)

```bash
gh release upload models --clobber \
  ml/classify/artifacts/importance_model.onnx \
  ml/time/artifacts/time_window_model.onnx \
  ml/dedup/artifacts/embed_model.onnx
```

После смены ONNX пересоберите bot-образ: новый тег `v*` (или перезапуск workflow).

---

## Релиз приложения

```bash
git tag v1.0.0
git push origin v1.0.0
```

Actions скачает Release `models`, соберёт и запушит три образа с тегами `v1.0.0` и `latest`,
затем сделает пакеты в GHCR **public** (pull без `docker login`).

---

## Запуск prod compose

1. Корневой `.env` — **только** эти три секрета:

```dotenv
MAX_BOT_TOKEN=...
CLOUDPUB_TOKEN=...
AITUNNEL_API_KEY=...
```

   Остальное (БД, порты, `APP_ENVIRONMENT=prod`) задано в `docker-compose.prod.yaml`.

2. Поднять стек **из корня репо** (образы публичные — логин в GHCR не нужен):

```bash
docker compose -f deploy/docker-compose.prod.yaml --env-file .env up -d

# конкретный релиз:
# IMAGE_TAG=v1.0.0 docker compose -f deploy/docker-compose.prod.yaml --env-file .env up -d
```

- Bot: `APP_ENVIRONMENT=prod` (конфиг `conf/prod.yaml`)
- Webapp: http://localhost:5173 (nginx :80 в контейнере)
- API: http://localhost:8000 (и `/api` через webapp)
- CloudPub: `docker compose -f deploy/docker-compose.prod.yaml logs -f cloudpub`
