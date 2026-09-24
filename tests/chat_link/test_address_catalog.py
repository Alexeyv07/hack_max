from address.components import clean_city_label, clean_district_label, parse_address_text
from address.street_catalog import CatalogAddress, StreetCatalog, normalize_ui_text
from chat_link.commands.keyboards import list_keyboard, prefix_groups
from chat_link.commands.pagination import HOUSE_PAGE_SIZE, PAGE_SIZE, paginate


def row(id, district, street, house, postal="123456"):
    return CatalogAddress(
        id=id,
        address_text=f"Москва, {district}, {street}, д. {house}",
        postal_code=postal,
        city="Москва",
        district=district,
        street=street,
        house=house,
        latitude=55.75 + id / 10000,
        longitude=37.6,
    )


def catalog(rows):
    return StreetCatalog([], addresses=rows)


def test_hierarchy_and_postal_filter_are_in_memory() -> None:
    index = catalog(
        [
            row(1, "ЦАО", "Тверская улица", "2"),
            row(2, "ЦАО", "Тверская улица", "10"),
            row(3, "САО", "Ленинградский проспект", "1", "654321"),
        ]
    )
    assert index.cities(postal_code="123456") == ["Москва"]
    assert index.districts("Москва", postal_code="123456") == ["ЦАО"]
    assert index.streets("Москва", "ЦАО", postal_code="123456") == ["Тверская улица"]
    assert [item.house for item in index.houses("Москва", "ЦАО", "Тверская улица")] == [
        "2",
        "10",
    ]


def test_picker_hierarchy_uses_prebuilt_indexes(monkeypatch) -> None:
    index = catalog(
        [
            row(1, "Ростокино", "Сельскохозяйственная улица", "15 к1", "129226"),
            row(2, "Ростокино", "Сельскохозяйственная улица", "17", "129226"),
        ]
    )

    def fail_filter(*args, **kwargs):
        raise AssertionError("picker не должен сканировать address snapshot после прогрева")

    monkeypatch.setattr(index, "_filtered_addresses", fail_filter)
    assert index.cities() == ["Москва"]
    assert index.districts("Москва") == ["Ростокино"]
    assert index.streets("Москва", "Ростокино") == ["Сельскохозяйственная улица"]
    assert [
        item.house for item in index.houses("Москва", "Ростокино", "Сельскохозяйственная улица")
    ] == [
        "15 к1",
        "17",
    ]
    assert index.postal_streets("129226") == ["Сельскохозяйственная улица"]


def test_webapp_postal_lookup_filters_and_paginates_in_memory() -> None:
    index = catalog(
        [
            row(1, "Ростокино", "Сельскохозяйственная улица", "15 к1", "129226"),
            row(2, "Ростокино", "Сельскохозяйственная улица", "17", "129226"),
            row(3, "Останкинский", "улица Академика Королёва", "1", "129226"),
            row(4, "Ростокино", "Сельскохозяйственная улица", "19", "129128"),
        ]
    )
    first, total = index.postal_addresses("129226", limit=2)
    second, another_total = index.postal_addresses("129226", offset=2, limit=2)
    assert total == another_total == 3
    assert {item.id for item in first + second} == {1, 2, 3}
    filtered, count = index.postal_addresses("129226", query="сельск 15")
    assert count == 1
    assert [item.id for item in filtered] == [1]
    assert index.postal_addresses("000000") == ([], 0)
    assert index.postal_addresses("129128", query="королева") == ([], 0)


def test_webapp_postal_endpoint_returns_total(monkeypatch) -> None:
    from chat_link.api import routes

    index = catalog([row(1, "Ростокино", "Сельскохозяйственная улица", "15", "129226")])
    monkeypatch.setattr(routes, "get_address_catalog", lambda: index)
    result = routes.search_postal_addresses("129226", q="сельск", offset=0, limit=12)
    assert result.total == 1
    assert [item.id for item in result.items] == [1]


def test_webapp_postal_endpoint_validates_code_and_page(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from chat_link.api import routes
    from events.api.app import create_app

    index = catalog([row(1, "Ростокино", "Сельскохозяйственная улица", "15", "129226")])
    monkeypatch.setattr(routes, "get_address_catalog", lambda: index)
    client = TestClient(create_app())
    valid = client.get("/chat-link/addresses/postal", params={"code": "129226"})
    assert valid.status_code == 200
    assert valid.json()["total"] == 1
    for params in (
        {"code": "12922"},
        {"code": "12922а"},
        {"code": "129226", "offset": -1},
        {"code": "129226", "limit": 31},
    ):
        assert client.get("/chat-link/addresses/postal", params=params).status_code == 422


def test_locality_labels_hide_source_noise() -> None:
    assert clean_city_label("Moscow") == "Москва"
    assert clean_city_label("Город не указан") is None
    assert clean_district_label("Moscow", city="Москва") is None
    assert clean_district_label("Город не указан", city="Москва") is None
    assert clean_district_label("Жилой комплекс Green Park", city="Москва") is None
    assert clean_district_label("район Ростокино", city="Москва") == "Ростокино"


def test_unicode_and_zero_width_normalization() -> None:
    assert normalize_ui_text("  ТВЕРСКАЯ\u200b   Ёлка ") == "тверская елка"


def test_fixed_pagination_and_fast_prefix_groups() -> None:
    page = paginate([str(i) for i in range(101)], 5)
    assert PAGE_SIZE == 10
    assert page.index == 5
    assert page.pages == 11
    assert len(page.items) == 10
    groups = prefix_groups(["Авиамоторная", "Арбат", "Беговая", "Бибиревская", "Вавилова"])
    assert 3 <= len(groups) <= 12


def test_house_keyboard_uses_three_columns_without_a_dangling_row() -> None:
    values = [str(index) for index in range(1, 17)]
    markup, page, pages = list_keyboard(values, kind="house", page=0, back="street")
    assert HOUSE_PAGE_SIZE == 15
    assert page == 0
    assert pages == 2
    rows = markup.payload.buttons
    assert [len(row) for row in rows[:5]] == [3, 3, 3, 3, 3]
    assert [button.text for button in rows[5]] == ["·", "1 / 2", "›"]
    assert rows[6][0].text == "← Назад"


def test_street_keyboard_is_capped_at_ten_rows() -> None:
    values = [f"Улица {index}" for index in range(11)]
    markup, page, pages = list_keyboard(values, kind="street", page=0, back="district")

    assert page == 0
    assert pages == 2
    rows = markup.payload.buttons
    assert [row[0].text for row in rows[:10]] == values[:10]
    assert [button.text for button in rows[10]] == ["·", "1 / 2", "›"]
    assert rows[11][0].text == "← Назад"


def test_long_keyboard_has_five_page_jump() -> None:
    values = [f"Улица {index}" for index in range(170)]
    markup, page, pages = list_keyboard(values, kind="street", page=6, back="district")

    assert page == 6
    assert pages == 17
    nav = markup.payload.buttons[10]
    assert [button.text for button in nav] == ["«5", "‹", "7 / 17", "›", "5»"]
    assert nav[0].payload == "cl:street:page:1"
    assert nav[4].payload == "cl:street:page:11"


def test_map_does_not_select_a_house_far_from_cursor() -> None:
    index = catalog([row(1, "ЦАО", "Тверская улица", "2")])
    assert index.nearest(59.93, 30.31) == []


def test_postal_picker_filters_directly_to_street_and_house() -> None:
    index = catalog(
        [
            row(1, "Ростокино", "Сельскохозяйственная улица", "15 к1", "129226"),
            row(2, "Останкинский", "улица Академика Королёва", "1", "129226"),
            row(3, "Ростокино", "Сельскохозяйственная улица", "17", "129128"),
        ]
    )
    assert index.postal_streets("129226") == [
        "Сельскохозяйственная улица",
        "улица Академика Королёва",
    ]
    assert [item.house for item in index.postal_houses("129226", "Сельскохозяйственная улица")] == [
        "15 к1"
    ]


def test_district_picker_never_exposes_unknown_placeholder() -> None:
    index = catalog(
        [
            row(1, "Ростокино", "Сельскохозяйственная улица", "15"),
            CatalogAddress(
                id=2,
                address_text="Москва, проспект Мира, д. 100",
                postal_code="129626",
                city="Москва",
                district=None,
                street="проспект Мира",
                house="100",
                latitude=55.8,
                longitude=37.63,
            ),
        ]
    )

    assert index.districts("Москва") == ["Ростокино"]
    assert "Район не указан" not in index.districts("Москва")


def test_address_search_autocompletes_partial_street_and_house() -> None:
    index = catalog(
        [
            row(1, "Ростокино", "Сельскохозяйственная улица", "15 к1", "129226"),
            row(2, "Ростокино", "Сельскохозяйственная улица", "17", "129226"),
            row(3, "Останкинский", "улица Академика Королёва", "1", "129515"),
        ]
    )

    street_hits = index.search("сельск", limit=10)
    assert [item.id for item, _score in street_hits] == [1, 2]

    house_hits = index.search("сельск 15", limit=10)
    assert [item.id for item, _score in house_hits] == [1]

    district_hits = index.search("росток сельск", limit=10)
    assert [item.id for item, _score in district_hits] == [1, 2]


def test_address_search_accepts_free_word_order_abbreviations_and_typos() -> None:
    index = catalog(
        [
            row(1, "Ростокино", "Сельскохозяйственная улица", "15 к1", "129226"),
            row(2, "Ростокино", "Сельскохозяйственная улица", "17", "129226"),
            row(3, "Останкинский", "улица Академика Королёва", "15", "129515"),
            row(4, "Пресненский", "улица 1905 года", "10", "123100"),
            row(5, "Тверской", "1-я Тверская-Ямская улица", "12", "125047"),
        ]
    )

    expected_first = {
        "15 сельск": 1,
        "ул сельск 15": 1,
        "сельск дом 15": 1,
        "ростокино 15 сельск": 1,
        "сльскохозяйственная 15": 1,  # опечатка уже в начале слова
        "сельск 15к1": 1,
        "живу на сельск 15": 1,
        "акад королева 15": 3,
        "1905 года": 4,  # число — часть улицы, а не дом
        "1 тверская 12": 5,
    }
    for query, expected_id in expected_first.items():
        hits = index.search(query, limit=10)
        assert hits, query
        assert hits[0][0].id == expected_id, query


def test_address_search_does_not_offer_wrong_house_when_number_is_house_hint() -> None:
    index = catalog(
        [
            row(1, "Ростокино", "Сельскохозяйственная улица", "15 к1"),
            row(2, "Ростокино", "Сельскохозяйственная улица", "17"),
        ]
    )

    assert [item.id for item, _score in index.search("сельск 15", limit=10)] == [1]


def test_duplicate_house_suffix_is_not_shown_as_part_of_street() -> None:
    parsed = parse_address_text("Москва, 1-й Сельскохозяйственный проезд 2 с1, д. 2 с1")
    assert parsed.street == "1-й Сельскохозяйственный проезд"
    assert parsed.house == "2 с1"


def test_free_search_treats_slash_corpus_and_building_as_same_secondary_number() -> None:
    index = catalog(
        [
            row(1, "Ростокино", "Сельскохозяйственная улица", "15 к1", "129226"),
            row(2, "Ростокино", "Сельскохозяйственная улица", "17", "129226"),
        ]
    )

    for query in (
        "сельскохозяйственная 15/1",
        "сельскохозяйственная 15к1",
        "сельскохозяйственная 15 корпус 1",
        "сельскохозяйственная 15с1",
        "сельскохозяйственная 15 строение 1",
    ):
        hits = index.search(query, limit=10)
        assert hits, query
        assert hits[0][0].id == 1, query


def test_obvious_compound_house_suffix_is_removed_even_if_house_field_is_dirty() -> None:
    parsed = parse_address_text("Москва, Сельскохозяйственная улица 4 с18, д. 4 с14")
    assert parsed.street == "Сельскохозяйственная улица"


def test_numeric_street_name_is_not_removed_by_fallback_cleanup() -> None:
    parsed = parse_address_text("Москва, улица 1905 года, д. 4")
    assert parsed.street == "улица 1905 года"
