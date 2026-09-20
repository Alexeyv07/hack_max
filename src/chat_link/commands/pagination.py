from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

PAGE_SIZE = 10
HOUSE_PAGE_SIZE = 15
JUMP_PAGES = 5


@dataclass(frozen=True, slots=True)
class Page[T]:
    """Одна страница со стабильным размером и абсолютными индексами исходного списка."""

    items: tuple[tuple[int, T], ...]
    index: int
    pages: int

    @property
    def has_previous(self) -> bool:
        return self.index > 0

    @property
    def has_next(self) -> bool:
        return self.index + 1 < self.pages


def paginate[T](
    values: Sequence[T],
    page: int,
    *,
    page_size: int = PAGE_SIZE,
) -> Page[T]:
    """Вернуть нормализованную страницу с абсолютными индексами исходного списка."""
    if page_size <= 0:
        raise ValueError("page_size должен быть положительным")

    pages = max(1, math.ceil(len(values) / page_size))
    index = max(0, min(page, pages - 1))
    start = index * page_size
    end = start + page_size
    return Page(
        items=tuple(enumerate(values[start:end], start=start)),
        index=index,
        pages=pages,
    )
