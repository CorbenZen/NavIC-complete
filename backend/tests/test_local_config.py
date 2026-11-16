import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.python_fastapi.application.core.config import DEFAULT_DATABASE_URL, Settings
from navic_tcp.db import normalize_database_url
from navic_tcp.local_paths import default_database_path, default_database_url, prepare_local_database


class LocalDatabaseConfigurationTests(unittest.TestCase):
    def test_default_is_absolute_sqlite_in_local_application_data(self):
        self.assertTrue(DEFAULT_DATABASE_URL.startswith("sqlite:////"))
        self.assertEqual(Path(default_database_path()).name, "navic.sqlite3")

    def test_data_directory_override_is_honored(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"NAVIC_DATA_DIR": directory}):
            self.assertEqual(default_database_path(), Path(directory) / "navic.sqlite3")

    def test_custom_database_url_and_postgres_normalization_remain_available(self):
        custom = "sqlite:////tmp/navic-test.sqlite3"
        with patch.dict(os.environ, {"DATABASE_URL": custom}, clear=False):
            self.assertEqual(Settings.from_environment().database_url, custom)
        self.assertEqual(
            normalize_database_url("postgres://user:pass@db.example/navic"),
            "postgresql+psycopg://user:pass@db.example/navic",
        )

    def test_legacy_database_is_copied_once_without_modifying_source(self):
        import sqlite3

        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "old.db"
            with sqlite3.connect(source) as connection:
                connection.execute("CREATE TABLE preserved (value TEXT NOT NULL)")
                connection.execute("INSERT INTO preserved VALUES ('existing record')")
            data_dir = root / "data"
            with patch.dict(os.environ, {"NAVIC_DATA_DIR": str(data_dir)}):
                url = default_database_url()
                target = prepare_local_database(url, source)
                self.assertEqual(target, data_dir / "navic.sqlite3")
                with sqlite3.connect(target) as connection:
                    self.assertEqual(connection.execute("SELECT value FROM preserved").fetchone()[0], "existing record")
                self.assertTrue(source.exists())
                self.assertIsNone(prepare_local_database(url, source))


if __name__ == "__main__":
    unittest.main()
