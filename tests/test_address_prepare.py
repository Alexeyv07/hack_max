import json
import tempfile
import unittest
from pathlib import Path

from address.gar_postcodes import house_key, lookup, street_key
from address.prepare_osm import convert_element, deduplicate, prepare
from address.seed import read_addresses


def element(identifier=1, **tags):
    return {
        "type": "way",
        "id": identifier,
        "center": {"lat": 55.75, "lon": 37.6},
        "tags": {
            "addr:street": "улица Тестовая",
            "addr:housenumber": "1",
            "building": "apartments",
            **tags,
        },
    }


class PreparationTests(unittest.TestCase):
    def test_house_components_are_exact_and_unsupported_syntax_rejected(self):
        self.assertEqual(house_key("д. 7 к2 с3"), ("7", "2", "3"))
        self.assertEqual(house_key("7А/2"), ("7а/2", None, None))
        self.assertIsNone(house_key("вл. 7"))
        self.assertIsNone(house_key("7-9"))
        self.assertNotEqual(house_key("7"), house_key("7 к2"))

    def test_exact_street_house_and_coordinates_required(self):
        key = (street_key("улица Тестовая"), house_key("1"))
        index = {key: [("guid", "123456", 55.75, 37.6)]}
        self.assertEqual(lookup(index, "Тестовая ул.", "1", 55.75, 37.6)["postal_code"], "123456")
        self.assertIsNone(lookup(index, "Тестовая улица", "2", 55.75, 37.6))
        self.assertIsNone(lookup(index, "Тестовая улица", "1", 55, 37))
        self.assertIsNone(lookup(index, "Тестовый проезд", "1", 55.75, 37.6))

    def test_ambiguity_does_not_choose_nearest_house(self):
        key = (street_key("улица Тестовая"), house_key("1"))
        index = {key: [("one", "123456", 55.75, 37.6), ("two", None, 55.75001, 37.6)]}
        self.assertIsNone(lookup(index, "улица Тестовая", "1", 55.75, 37.6))

    def test_same_guid_reached_through_two_parents_is_not_ambiguous(self):
        key = (street_key("улица Тестовая"), house_key("1"))
        row = ("guid", "123456", 55.75, 37.6)
        self.assertIsNotNone(lookup({key: [row, row]}, "улица Тестовая", "1", 55.75, 37.6))

    def test_conflicting_primary_keys_are_quarantined(self):
        first = convert_element(element())
        other = dict(first, latitude=56, source_key="osm:way/2")
        rows, rejected = deduplicate([first, other])
        self.assertEqual(rows, [])
        self.assertEqual(len(rejected[0]["rows"]), 2)

    def test_identical_duplicates_keep_provenance(self):
        rows, rejected = deduplicate([convert_element(element(2)), convert_element(element(1))])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_keys"], ["osm:way/1", "osm:way/2"])
        self.assertEqual(rejected, [])

    def test_osm_conversion_keeps_locality_and_unknown_postcode(self):
        row = convert_element(element(**{"addr:city": "Троицк", "addr:postcode": "12345"}))
        self.assertEqual(row["address_text"], "Москва, Троицк, улица Тестовая, д. 1")
        self.assertIsNone(row["postal_code"])
        self.assertIs(row["is_private"], False)

    def test_prepared_file_is_importable_and_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            output = Path(directory) / "result"
            source.write_text(json.dumps({"elements": [element()]}))
            first = prepare(source, output)
            second = prepare(source, output)
            self.assertEqual(first, second)
            self.assertEqual(len(read_addresses(output / "moscow.jsonl.gz")), 1)
            self.assertEqual(first["without_postcode"], 1)

    def test_overpass_partial_response_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            source.write_text(json.dumps({"elements": [element()], "remark": "timeout"}))
            with self.assertRaises(ValueError):
                prepare(source, Path(directory) / "result")
