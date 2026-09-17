import gzip
import json
import tempfile
import unittest
from pathlib import Path

from address.seed import read_addresses


class AddressFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "addresses.jsonl"
        self.row = {
            "address_text": "Москва, улица Тестовая, д. 1",
            "latitude": 55.7,
            "longitude": 37.6,
            "postal_code": "123456",
            "is_private": False,
        }

    def write(self, rows):
        self.path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def test_same_address_with_different_data_is_rejected(self):
        self.write([self.row, dict(self.row, latitude=56)])
        with self.assertRaisesRegex(ValueError, "Строка 2"):
            read_addresses(self.path)

    def test_identical_duplicates_and_external_metadata(self):
        self.write([self.row, dict(self.row, source_key="osm:way/1")])
        self.assertEqual(len(read_addresses(self.path)), 1)

    def test_parses_city_street_house_from_address_text(self):
        self.write([self.row])
        loaded = read_addresses(self.path)[0]
        self.assertEqual(loaded["city"], "Москва")
        self.assertEqual(loaded["street"], "улица Тестовая")
        self.assertEqual(loaded["house"], "1")

    def test_explicit_components_override_parse(self):
        self.write(
            [
                dict(
                    self.row,
                    city="Казань",
                    street="ул. Баумана",
                    house="2",
                )
            ]
        )
        loaded = read_addresses(self.path)[0]
        self.assertEqual(loaded["city"], "Казань")
        self.assertEqual(loaded["street"], "ул. Баумана")
        self.assertEqual(loaded["house"], "2")

    def test_missing_postcode_and_unknown_house_type_are_allowed(self):
        self.write([dict(self.row, postal_code=None, is_private=None)])
        self.assertIsNone(read_addresses(self.path)[0]["postal_code"])

    def test_invalid_values_and_empty_file_are_rejected(self):
        for change in (
            {"latitude": "NaN"},
            {"longitude": 181},
            {"latitude": True},
            {"postal_code": 123456},
            {"is_private": 1},
            {"address_text": " "},
        ):
            with self.subTest(change=change):
                self.write([dict(self.row, **change)])
                with self.assertRaises(ValueError):
                    read_addresses(self.path)
        self.write([])
        with self.assertRaises(ValueError):
            read_addresses(self.path)

    def test_gzip_input(self):
        path = self.path.with_suffix(".jsonl.gz")
        with gzip.open(path, "wt") as out:
            out.write(json.dumps(self.row) + "\n")
        self.assertEqual(read_addresses(path)[0]["address_text"], self.row["address_text"])
