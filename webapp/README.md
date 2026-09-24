# WebApp (SvelteKit mini-app)

Лента событий + chat_link. HTTPS для Max — CloudPub.

| Где      | URL                                                                                     |
|----------|-----------------------------------------------------------------------------------------|
| Локально | http://localhost:5173                                                                   |
| Max      | `https://incompletely-immortal-ling.cloudpub.ru` (`CLOUDPUB_TOKEN` в `.env`) |

`/api` → Vite proxy на `:8000`. На localhost user id = `159064979`.
Yandex Maps: `YANDEX_MAPS_API_KEY` в `src/lib/yandexMaps.ts`.

## Запуск

```bash
# всё в Docker
docker compose up -d --build

# бот на хосте
docker compose up -d postgres webapp cloudpub
python -m main
```

Нужен `CLOUDPUB_TOKEN` в корневом `.env` ([cloudpub.ru](https://cloudpub.ru)).

Только фронт: `npm install && npm run dev`.

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

Выбор адреса: четыре кнопки в боте (два способа в чате, карта и текстовый WebApp).
В текстовом WebApp остался быстрый fuzzy-поиск, вкладка индекса не показывается: индекс
указывается в боте и ведёт сразу к улице и дому. Оба WebApp-варианта после подтверждения
создают новую главную в MAX с фото и актуальными адресами.

Выбор личного дома подтверждается через `/chat-link/select` и сохраняется независимо от групп.
В контекстах группы (`chat_id`/`resident_chat_id`) отдельно проверяются права и членство.

Проверка KAN-18: открыть `chat_link_text` → найти дом текстом → подтвердить; индекс проверить отдельно в боте; открыть `chat_link_map` →
передвинуть карту → выбрать ближайший дом → подтвердить. Для admin bind результат
привязывает адрес к указанной группе, для resident — выбирает дом среди адресов
группы. Обычный выбор сохраняет `users.address_id` и возвращает `personal_address`:
лента рядом работает сразу, подключать чат не обязательно.

Карта — Yandex Maps JS API 3.0; ключ зашит в `yandexMaps.ts`. Адреса и nearest lookup
через backend `StreetCatalog`, Yandex — только подложка карты.

Для подключения чата администратор добавляет бота в группу и открывает deep-link
из сообщения бота в группе. Основной личный сценарий не предлагает добавлять группу.
