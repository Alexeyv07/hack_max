"""Тесты очистки body и enrich_from_html без сети."""

from __future__ import annotations

from parse_news.sources.common import enrich_from_html
from parser_common.body_text import clean_article_body, is_boilerplate_body


def test_boilerplate_podrobnee() -> None:
    assert is_boilerplate_body("Подробнее на сайте")
    assert clean_article_body("Подробнее на сайте") is None
    assert clean_article_body("Подробнее на сайте.") is None


def test_clean_strips_suffix_keeps_substance() -> None:
    text = (
        "Средства ПВО уничтожили еще восемь беспилотников, "
        "летевших в сторону Москвы. Подробнее на сайте"
    )
    cleaned = clean_article_body(text)
    assert cleaned is not None
    assert "ПВО" in cleaned
    assert "Подробнее" not in cleaned


def test_clean_drops_body_equal_title() -> None:
    title = "Взрыв в центре города"
    assert clean_article_body(title, title=title) is None
    assert clean_article_body(f"{title}. Подробнее на сайте", title=title) is None


def test_enrich_prefers_article_over_og_stub() -> None:
    html = """
    <html><head>
      <meta property="og:title" content="Число сбитых дронов достигло 29" />
      <meta property="og:description" content="Подробнее на сайте" />
    </head><body>
      <article class="doc">
        <div class="doc__text">
          <p>Средства ПВО уничтожили еще восемь беспилотников,
          летевших в сторону Москвы.</p>
          <p>Об этом сообщил мэр столицы.</p>
        </div>
      </article>
    </body></html>
    """
    article = enrich_from_html(
        html,
        outlet="kommersant",
        url="https://www.kommersant.ru/doc/1",
        external_id="1",
    )
    assert article.body is not None
    assert "ПВО" in article.body
    assert "Подробнее" not in article.body
    assert article.title.startswith("Число сбитых")
