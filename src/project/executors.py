"""Пулы потоков: API/бот не делят очередь с тяжёлыми парсерами (ONNX/spaCy)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial

# Мало воркеров: ONNX CPU-bound; не забиваем GIL и пул БД.
PARSER_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="parser_ml")

# Новости и ЖЭК не гоняют ML одновременно — иначе TTFB API улетает в десятки секунд.
PARSER_ML_SEM = asyncio.Semaphore(1)


async def run_in_parser_pool[**P, T](
    fn: Callable[P, T],
    /,
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Выполнить sync-работу парсера в отдельном пуле (не default to_thread)."""
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(PARSER_EXECUTOR, partial(fn, *args, **kwargs))
    return await loop.run_in_executor(PARSER_EXECUTOR, fn, *args)
