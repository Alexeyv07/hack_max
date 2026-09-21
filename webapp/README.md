# WebApp (SvelteKit mini-app)

Статический фронт для Max: лента событий + chat_link (карта / текст).

## Локально

Нужен backend на `:8000` (`python -m main`).

```bash
cd webapp
cp .env.example .env   # PUBLIC_API_BASE=/api
npm install
npm run dev            # http://localhost:5173
```

- `/api/*` проксируется на `API_PROXY_TARGET` (по умолчанию `http://127.0.0.1:8000`).
- На `localhost` / `127.0.0.1` user id **всегда** `159064979` (не из Max Bridge).
- На GitHub Pages / в Max — id из Bridge (`initDataUnsafe` / `initData` / hash).

## Релиз → GitHub Pages

Триггер: тег `v*` или Actions → **WebApp Pages**.

1. Repo **variable** `WEBAPP_API_BASE` = публичный origin API (например `https://api.example.com`).
2. Опционально secret `VITE_YANDEX_MAPS_API_KEY`.
3. `git tag v0.1.0 && git push origin v0.1.0`

Сборка с `BASE_PATH=/hack_max` → https://alexeyv07.github.io/hack_max/  
В настройках бота Max укажите этот URL.

CORS на API должен разрешать `https://alexeyv07.github.io` (`api.cors_origins` / `API_CORS_ORIGINS`).

## KAN-7 address picker

При `start_param=chat_link_map` WebApp показывает карту и ближайшие дома из локального
`StreetCatalog`; при `start_param=chat_link_text` — живые подсказки уже по части адреса. Оба
режима вызывают `/chat-link/select` и продолжают тот же flow подключения группового чата,
что бот. Незавершённый picker сохраняет черновик в `localStorage` на 30 минут, а активный
address-mode кешируется отдельно. Поэтому reload или пересоздание текущего WebView не сбрасывает
введённый текст, положение карты или выбранный дом и не заставляет flow снова проходить экран
«Открываем…». После успешного выбора черновик очищается: новое открытие начинается с нового
адреса; на экране результата также есть кнопка «Добавить ещё адрес».

Поиск адресов и nearest lookup публичные и не требуют user id. Он нужен только при финальном
`/chat-link/select`: на localhost — `159064979`, в Max — Bridge
(`initDataUnsafe` → `initData` → `WebAppData` во fragment). MAX Bridge подключается из
`https://st.max.ru/js/max-web-app.js`.

Карта рендерится через Yandex Maps JS API 3.0; ключ приходит из `VITE_YANDEX_MAPS_API_KEY`.
Адреса и nearest lookup остаются локальными через backend `StreetCatalog`, Yandex используется
только как интерактивная подложка карты.

После выбора дома экран по умолчанию показывает сценарий обычного жителя. Кнопка
`Я администратор чата` раскрывает отдельную админскую инструкцию, не меняя стартовый flow MiniApp.
