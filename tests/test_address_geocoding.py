import unittest
from decimal import Decimal

from address.geocoding import GeoMatcher, normalize_address
from address.models.address import Address


def address(text, postcode="123456", latitude="55.75", address_id=1):
    return Address(address_id, postcode, text, Decimal(latitude), Decimal("37.60"))


class GeocodingTests(unittest.TestCase):
    def setUp(self):
        self.first = address("Москва, улица Ленина, д. 10 к2")
        self.second = address("Москва, улица Ленина, д. 10 с2", latitude="55.76")
        self.chat = (Decimal("55.70"), Decimal("37.50"))

    def test_normalizes_case_yo_and_abbreviations(self):
        self.assertEqual(normalize_address("УЛ.ЗЕЛЁНАЯ, Д.10 К2"), "улица зеленая дом 10 корпус 2")
        self.assertEqual(normalize_address("пр-т Мира"), normalize_address("проспект Мира"))

    def test_unique_postcode_lookup(self):
        result = GeoMatcher([self.first]).resolve("Индекс: 123456")
        self.assertEqual(result.address_text, self.first.address_text)
        self.assertEqual(result.address_id, self.first.id)
        self.assertEqual((result.scope, result.method, result.score), ("address", "postcode", 100))

    def test_repeated_postcode_does_not_pick_a_random_house(self):
        result = GeoMatcher([self.first, self.second]).resolve("123456", chat_coordinates=self.chat)
        self.assertEqual(result.scope, "chat")
        self.assertEqual((result.latitude, result.longitude), self.chat)

    def test_postcode_and_house_select_correct_corpus(self):
        result = GeoMatcher([self.first, self.second]).resolve("123456, ул. Ленина, д.10 к2")
        self.assertEqual(result.address_text, self.first.address_text)

    def test_explicit_house_mismatch_does_not_fall_back_to_another_house(self):
        result = GeoMatcher([self.first]).resolve("На ул. Ленина, д. 10 с2 пожар")
        self.assertEqual(result.scope, "city")
        self.assertIsNone(result.latitude)

    def test_fuzzy_street_typo_with_exact_house(self):
        row = address("Москва, Ленинградский проспект, д. 8", postcode=None)
        result = GeoMatcher([row]).resolve("На Ленингрдский пр-т, д.8 отключили воду")
        self.assertEqual(result.address_text, row.address_text)
        self.assertEqual(result.method, "fuzzy")
        self.assertGreaterEqual(result.score, 90)

    def test_no_house_on_multi_house_street_is_ambiguous(self):
        result = GeoMatcher([self.first, self.second]).resolve("На ул. Ленина отключили воду")
        self.assertEqual(result.scope, "city")

    def test_different_street_types_are_not_interchangeable(self):
        row = address("Москва, проспект Ленина, д. 10 к2")
        result = GeoMatcher([row]).resolve("На ул. Ленина д. 10 к2")
        self.assertEqual(result.scope, "city")

    def test_numbered_streets_do_not_match_by_similar_name(self):
        row = address("Москва, 1-я Парковая улица, д. 8")
        result = GeoMatcher([row]).resolve("На 2-й Парковой улице, д. 8")
        self.assertEqual(result.scope, "city")

    def test_several_mentioned_addresses_are_ambiguous(self):
        result = GeoMatcher([self.first, self.second]).resolve("ул. Ленина д. 10 к2 и д. 10 с2")
        self.assertEqual(result.scope, "city")

    def test_unrelated_text_and_empty_scope_fall_back(self):
        for rows, text in (([self.first], "Доброе утро, соседи!"), ([], "123456")):
            with self.subTest(text=text):
                result = GeoMatcher(rows).resolve(text, chat_coordinates=self.chat)
                self.assertEqual(result.scope, "chat")
                self.assertEqual(result.method, "fallback")

    def test_postcode_inside_long_number_is_not_recognized(self):
        result = GeoMatcher([self.first]).resolve("Номер заявки 91234567")
        self.assertEqual(result.scope, "city")

    def test_unknown_postcode_does_not_expand_search(self):
        result = GeoMatcher([self.first]).resolve("654321, ул. Ленина д. 10 к2")
        self.assertEqual(result.scope, "city")

    def test_threshold_can_reject_weak_match(self):
        row = address("Москва, Ленинградский проспект, д. 8")
        result = GeoMatcher([row], threshold=100).resolve("Ленингрдский пр-т, д.8")
        self.assertEqual(result.scope, "city")

    def test_unsupported_house_syntax_is_not_silently_ignored(self):
        for text in ("улица Ленина 99", "ул. Ленина дом 10/2/3", "ул. Ленина дом 10 к2 к3"):
            with self.subTest(text=text):
                self.assertEqual(GeoMatcher([self.first]).resolve(text).scope, "city")

    def test_correct_numbered_street_matches(self):
        row = address("Москва, 1-я Парковая улица, д. 8")
        self.assertEqual(
            GeoMatcher([row]).resolve("На 1-я Парковая ул., д.8").address_text, row.address_text
        )


if __name__ == "__main__":
    unittest.main()
