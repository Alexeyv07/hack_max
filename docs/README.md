# Документация (mdBook)

Книга собирается из `docs/src/` и публикуется на GitHub Pages:

`https://alexeyv07.github.io/hack_max/docs/`

## Локальный запуск

### 1. Установить mdBook (+ mermaid, опционально)

```bash
cargo install mdbook --locked
cargo install mdbook-mermaid
mdbook-mermaid install docs
```

Или скачать бинарник с [релизов mdBook](https://github.com/rust-lang/mdBook/releases).

Проверка:

```bash
mdbook --version
```

### 2. Live-preview с автопересборкой

Из корня репозитория:

```bash
cd docs
mdbook serve --open
```

Откроется `http://localhost:3000`. При сохранении `.md` страница обновится сама.

### 3. Только собрать статику

```bash
mdbook build docs
```

Результат — `docs/book/` (в git не коммитится).

### 4. Проверить перед пушем

```bash
mdbook build docs
```

На `main` workflow `.github/workflows/mdbook.yaml` пушит HTML в ветку `gh-pages`
в каталог `docs/` (`destination_dir: docs`).
