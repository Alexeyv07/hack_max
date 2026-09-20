from address.components import clean_city_label, clean_district_label
from address.street_catalog import CatalogAddress, StreetCatalog, normalize_ui_text
from chat_link.commands.keyboards import list_keyboard, page_size, paginate, prefix_groups


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


def test_locality_labels_hide_source_noise() -> None:
    assert clean_city_label("Moscow") == "Москва"
    assert clean_city_label("Город не указан") is None
    assert clean_district_label("Moscow", city="Москва") is None
    assert clean_district_label("Город не указан", city="Москва") is None
    assert clean_district_label("Жилой комплекс Green Park", city="Москва") is None
    assert clean_district_label("район Ростокино", city="Москва") == "Ростокино"


def test_unicode_and_zero_width_normalization() -> None:
    assert normalize_ui_text("  ТВЕРСКАЯ\u200b   Ёлка ") == "тверская елка"


def test_adaptive_pagination_and_fast_prefix_groups() -> None:
    assert page_size(5) == 5
    assert page_size(25) == 6
    items, page, pages = paginate([str(i) for i in range(101)], 5)
    assert page == 5
    assert pages == 9
    assert len(items) <= 12
    groups = prefix_groups(["Авиамоторная", "Арбат", "Беговая", "Бибиревская", "Вавилова"])
    assert 3 <= len(groups) <= 12


def test_house_keyboard_uses_compact_grid() -> None:
    markup, page, pages = list_keyboard(
        ["1", "2", "3", "4", "5", "6", "7", "8", "9"],
        kind="house",
        page=0,
        back="street",
    )
    assert page == 0
    assert pages == 1
    rows = markup.payload.buttons
    # Девять коротких домов занимают три ряда по три, затем идёт «Назад».
    assert [len(row) for row in rows[:3]] == [3, 3, 3]
    assert rows[3][0].text == "← Назад"


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
