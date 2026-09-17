"""Интеграционные тесты финальной схемы address + events на PostgreSQL.

PYTHONPATH=src ADDRESS_TEST_DATABASE_URL=... python -m unittest tests.test_address_schema -v

Нужен PostgreSQL с правом CREATE SCHEMA. Все изменения тестов откатываются.
"""

import importlib.util
import os
import unittest
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations

from address.db import AddressRow
from address.db.queries import load_addresses
from address.geocoding import GeoMatcher
from address.seed import upsert_addresses
from auth.db import UserRow  # noqa: F401 — зарегистрировать users в metadata
from events.db import EventRow
from parse_news.db import NewsParserCursorRow  # noqa: F401
from project.database import Base


@unittest.skipUnless(os.getenv("ADDRESS_TEST_DATABASE_URL"), "Нужен ADDRESS_TEST_DATABASE_URL")
class AddressSchemaTests(unittest.TestCase):
    MIGRATIONS = (
        "0001_create_users",
        "0002_create_events",
        "0003_events_image_url",
        "0004_create_addresses",
        "0005_event_address_fk",
        "0006_news_parser",
        "0007_address_components_geo_by",
        "0008_events_published_at",
    )

    def setUp(self):
        self.engine = sa.create_engine(os.environ["ADDRESS_TEST_DATABASE_URL"])
        self.addCleanup(self.engine.dispose)
        self.connection = self.engine.connect()
        self.addCleanup(self.connection.close)
        transaction = self.connection.begin()
        self.addCleanup(transaction.rollback)
        schema = "address_test_" + uuid.uuid4().hex
        self.connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        self.connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        self.context = MigrationContext.configure(self.connection)
        self.migrations = [self.load_migration(name) for name in self.MIGRATIONS]
        with Operations.context(self.context):
            for migration in self.migrations:
                migration.upgrade()

    @staticmethod
    def load_migration(name):
        path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_migrations_match_models_and_can_be_reverted(self):
        self.assertEqual(compare_metadata(self.context, Base.metadata), [])
        inspector = sa.inspect(self.connection)
        self.assertEqual(inspector.get_pk_constraint("addresses")["constrained_columns"], ["id"])
        self.assertEqual(
            {item["name"] for item in inspector.get_unique_constraints("addresses")},
            {"uq_addresses_address_text"},
        )
        self.assertIn("address_id", {column["name"] for column in inspector.get_columns("events")})
        self.assertNotIn("lat", {column["name"] for column in inspector.get_columns("events")})
        self.assertNotIn("lon", {column["name"] for column in inspector.get_columns("events")})
        foreign_keys = inspector.get_foreign_keys("events")
        self.assertTrue(
            any(
                fk["constrained_columns"] == ["address_id"]
                and fk["referred_table"] == "addresses"
                and fk["referred_columns"] == ["id"]
                for fk in foreign_keys
            )
        )

        with Operations.context(self.context):
            for migration in reversed(self.migrations):
                migration.downgrade()
        self.assertEqual(sa.inspect(self.connection).get_table_names(), [])

    def test_address_primary_key_and_scoped_database_lookup(self):
        from sqlalchemy.orm import Session

        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            text = "Москва, улица Ленина, д. 10"
            session.add_all(
                [
                    AddressRow(address_text=text, postal_code="123456", latitude=55, longitude=37),
                    AddressRow(
                        address_text="Казань, улица Ленина, д. 10",
                        postal_code="123456",
                        latitude=56,
                        longitude=49,
                    ),
                ]
            )
            session.flush()
            address_id = session.scalar(
                sa.select(AddressRow.id).where(AddressRow.address_text == text)
            )
            self.assertIsNotNone(address_id)
            self.assertEqual(session.get(AddressRow, address_id).address_text, text)
            selected = load_addresses(session, address_texts=[text])
            self.assertEqual(len(selected), 1)
            self.assertEqual(load_addresses(session, address_texts=[]), [])
            result = GeoMatcher(selected).resolve("123456")
            self.assertEqual(result.address_text, text)
            self.assertEqual(result.address_id, address_id)
            with self.assertRaises(sa.exc.IntegrityError), self.connection.begin_nested():
                self.connection.execute(
                    sa.insert(AddressRow).values(address_text=text, latitude=55, longitude=37)
                )

    def test_event_references_address_instead_of_copying_coordinates(self):
        from sqlalchemy.orm import Session

        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            address = AddressRow(
                address_text="Москва, улица Событийная, д. 1",
                postal_code="123456",
                latitude=55.75,
                longitude=37.62,
            )
            session.add(address)
            session.flush()
            event = EventRow(
                title="Событие",
                body="Описание",
                importance=2,
                source="news",
                address_id=address.id,
                weight=0,
                disaster_flag=False,
            )
            session.add(event)
            session.flush()
            self.assertEqual(event.address_id, address.id)
            self.assertEqual(event.address.address_text, address.address_text)

    def test_same_postal_code_allows_different_houses(self):
        for number in (1, 2):
            self.connection.execute(
                sa.insert(AddressRow).values(
                    postal_code="129226",
                    address_text=f"Тестовый дом {number}",
                    latitude=55.84,
                    longitude=37.64,
                )
            )
        rows = self.connection.execute(sa.select(AddressRow.id, AddressRow.postal_code)).all()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0].id, rows[1].id)
        self.assertEqual(rows[0].postal_code, rows[1].postal_code)

    def test_seed_rerun_preserves_ids_and_known_postcode(self):
        from sqlalchemy.orm import Session

        row = dict(
            address_text="Тестовый дом",
            latitude=55,
            longitude=37,
            postal_code="123456",
            is_private=False,
        )
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            upsert_addresses(session, [row])
            first_id = session.scalar(sa.select(AddressRow.id))
            upsert_addresses(session, [dict(row, latitude=56, postal_code=None, is_private=None)])
            record = session.execute(
                sa.select(
                    AddressRow.id,
                    AddressRow.latitude,
                    AddressRow.postal_code,
                    AddressRow.is_private,
                )
            ).one()
            self.assertEqual(record.id, first_id)
            self.assertEqual(record.latitude, 56)
            self.assertEqual(record.postal_code, "123456")
            self.assertIs(record.is_private, False)

    def test_seed_failure_rolls_back_all_batches(self):
        from sqlalchemy.orm import Session

        rows = [
            dict(
                address_text=f"Дом {n}",
                latitude=55,
                longitude=37,
                postal_code=None,
                is_private=None,
            )
            for n in range(501)
        ]
        rows[-1]["latitude"] = 91
        with Session(bind=self.connection, join_transaction_mode="create_savepoint") as session:
            with self.assertRaises(sa.exc.IntegrityError), session.begin():
                upsert_addresses(session, rows)
            self.assertEqual(session.scalar(sa.select(sa.func.count()).select_from(AddressRow)), 0)

    def test_database_rejects_invalid_address_values(self):
        for invalid in (
            {"latitude": 91},
            {"longitude": -181},
            {"postal_code": "12345"},
            {"postal_code": "abcdef"},
            {"address_text": " "},
            {"latitude": None},
        ):
            with self.subTest(invalid=invalid):
                values = dict(
                    postal_code="129226", address_text="Тестовый дом", latitude=55, longitude=37
                )
                values.update(invalid)
                with self.assertRaises(sa.exc.IntegrityError), self.connection.begin_nested():
                    self.connection.execute(sa.insert(AddressRow).values(**values))


if __name__ == "__main__":
    unittest.main()
