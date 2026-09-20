# sv

Everything you need to build a Svelte project, powered by [`sv`](https://github.com/sveltejs/cli).

## Creating a project

If you're seeing this, you've probably already done this step. Congrats!

```sh
# create a new project
npx sv create my-app
```

To recreate this project with the same configuration:

```sh
# recreate this project
npx sv@0.17.0 create --template minimal --types ts --no-install webapp
```

## Developing

Once you've created a project and installed dependencies with `npm install` (or `pnpm install` or `yarn`), start a development server:

```sh
npm run dev

# or start the server and open the app in a new browser tab
npm run dev -- --open
```

## Building

To create a production version of your app:

```sh
npm run build
```

You can preview the production build with `npm run preview`.

> To deploy your app, you may need to install an [adapter](https://svelte.dev/docs/kit/adapters) for your target environment.


## KAN-7 address picker

При `start_param=chat_link_map` WebApp показывает карту и ближайшие дома из локального
`StreetCatalog`; при `start_param=chat_link_text` — живые подсказки уже по части адреса. Оба
режима вызывают `/api/chat-link/select` и продолжают тот же flow подключения группового чата,
что бот. Незавершённый picker сохраняет черновик в `localStorage` на 30 минут, а активный
address-mode кешируется отдельно. Поэтому reload или пересоздание текущего WebView не сбрасывает
введённый текст, положение карты или выбранный дом и не заставляет flow снова проходить экран
«Открываем…». После успешного выбора черновик очищается: новое открытие начинается с нового
адреса; на экране результата также есть кнопка «Добавить ещё адрес».
Поиск адресов и nearest lookup публичные и не требуют user id. Он нужен только при финальном
`/api/chat-link/select`: сначала читается `window.WebApp.initDataUnsafe.user.id`, затем официальный
`initData`, а при reload WebView — `WebAppData` из URL fragment. Тестового hardcode нет. MAX Bridge
подключается из официального CDN `https://st.max.ru/js/max-web-app.js`.

Карта рендерится через Yandex Maps JS API 3.0; ключ приходит из `VITE_YANDEX_MAPS_API_KEY`.
Адреса и nearest lookup остаются локальными через backend `StreetCatalog`, Yandex используется
только как интерактивная подложка карты.

После выбора дома экран по умолчанию показывает сценарий обычного жителя. Кнопка
`Я администратор чата` раскрывает отдельную админскую инструкцию, не меняя стартовый flow MiniApp.
