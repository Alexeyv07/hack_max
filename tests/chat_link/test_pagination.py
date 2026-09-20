from chat_link.commands.pagination import HOUSE_PAGE_SIZE, PAGE_SIZE, paginate


def test_page_sizes_keep_lists_compact() -> None:
    assert PAGE_SIZE == 10
    assert HOUSE_PAGE_SIZE == 15


def test_paginate_returns_absolute_indexes() -> None:
    values = [f"item-{index}" for index in range(50)]

    page = paginate(values, 2)

    assert page.index == 2
    assert page.pages == 5
    assert page.items == tuple((index, values[index]) for index in range(20, 30))


def test_paginate_clamps_page_bounds() -> None:
    values = list(range(20))

    assert paginate(values, -10).index == 0
    last = paginate(values, 100)
    assert last.index == last.pages - 1


def test_paginate_empty_sequence() -> None:
    page = paginate([], 4)

    assert page.index == 0
    assert page.pages == 1
    assert page.items == ()
