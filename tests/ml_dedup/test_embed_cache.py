"""Кэш эмбеддингов по content-hash."""

from __future__ import annotations

from ml_dedup.embed import clear_embed_cache, embed_text


def test_embed_text_cached_by_content_hash() -> None:
    clear_embed_cache()
    a = embed_text("Отключили воду на Лесной", allow_hash_fallback=True)
    b = embed_text("Отключили воду на Лесной", allow_hash_fallback=True)
    c = embed_text("  Отключили   воду на Лесной  ", allow_hash_fallback=True)
    assert a is b  # тот же объект из LRU
    assert c is a  # нормализация пробелов → тот же ключ


def test_embed_different_text_different_vec() -> None:
    clear_embed_cache()
    a = embed_text("Прорыв трубы на Лесной", allow_hash_fallback=True)
    b = embed_text("Концерт в парке Горького", allow_hash_fallback=True)
    assert a is not b
    assert len(a) == len(b)
    assert a != b
