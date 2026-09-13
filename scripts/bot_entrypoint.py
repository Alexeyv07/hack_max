"""Entrypoint контейнера бота: миграции, затем запуск polling."""

from __future__ import annotations

import sys

from alembic.config import main as alembic_main

from main import main as bot_main


def run() -> None:
    print("Применяем миграции Alembic...", flush=True)
    alembic_main(argv=["upgrade", "head"])
    print("Запускаем бота...", flush=True)
    bot_main()


if __name__ == "__main__":
    try:
        run()
    except SystemExit:
        raise
    except Exception:
        print("Ошибка entrypoint бота", file=sys.stderr, flush=True)
        raise
