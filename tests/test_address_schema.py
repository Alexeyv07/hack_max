"""PYTHONPATH=src ADDRESS_TEST_DATABASE_URL=... python -m unittest discover -s tests -v.

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
from auth.db import UserRow  # noqa: F401 — зарегистрировать users в metadata
from project.database import Base


@unittest.skipUnless(os.getenv("ADDRESS_TEST_DATABASE_URL"), "Нужен ADDRESS_TEST_DATABASE_URL")
class AddressSchemaTests(unittest.TestCase):
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
        self.migration = self.load_migration("0002_create_addresses")
        with Operations.context(self.context):
            self.load_migration("0001_create_users").upgrade()
            self.migration.upgrade()

    @staticmethod
    def load_migration(name):
        path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_migration_matches_models_and_can_be_reverted(self):
        self.assertEqual(compare_metadata(self.context, Base.metadata), [])
        with Operations.context(self.context):
            self.migration.downgrade()
            self.assertEqual(sa.inspect(self.connection).get_table_names(), ["users"])
            self.migration.upgrade()
        self.assertEqual(compare_metadata(self.context, Base.metadata), [])

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
