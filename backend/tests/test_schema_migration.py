"""Additive schema migration tests for legacy SQLite databases."""

import unittest

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from navic_tcp.schema import ensure_schema


class AdditiveSchemaTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE location_history ("
                    "id INTEGER PRIMARY KEY, device_id VARCHAR(64), message_id VARCHAR(36), "
                    "timestamp DATETIME, latitude FLOAT, longitude FLOAT, speed FLOAT, "
                    "course FLOAT, simulated BOOLEAN)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO location_history "
                    "(device_id, message_id, timestamp, latitude, longitude, speed, course, simulated) "
                    "VALUES ('legacy-device', 'legacy-message', '2026-01-01 00:00:00', 13.0, 80.0, 12.0, 90.0, 0)"
                )
            )
            connection.execute(
                text("CREATE TABLE tracking_devices (id INTEGER PRIMARY KEY, device_id VARCHAR(64) UNIQUE)")
            )
            connection.execute(text("INSERT INTO tracking_devices (device_id) VALUES ('legacy-device')"))

    def tearDown(self):
        self.engine.dispose()

    def test_missing_columns_are_added_without_dropping_rows(self):
        ensure_schema(self.engine)
        columns = {column["name"] for column in inspect(self.engine).get_columns("location_history")}
        self.assertTrue({"ignition", "odometer", "altitude_m", "gnss_metadata"} <= columns)
        device_columns = {column["name"] for column in inspect(self.engine).get_columns("tracking_devices")}
        self.assertIn("active", device_columns)
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT device_id, simulated FROM location_history")
            ).one()
            self.assertEqual(row.device_id, "legacy-device")
            active = connection.execute(text("SELECT active FROM tracking_devices")).scalar_one()
            self.assertEqual(bool(active), True)

    def test_running_ensure_schema_twice_is_safe(self):
        ensure_schema(self.engine)
        ensure_schema(self.engine)
        tables = set(inspect(self.engine).get_table_names())
        self.assertTrue({"location_history", "tracking_devices", "audit_logs", "system_settings"} <= tables)

    def test_email_verification_upgrade_preserves_users_and_prior_verified_state(self):
        legacy = create_engine("sqlite://")
        try:
            with legacy.begin() as connection:
                connection.execute(text(
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(120), "
                    "email VARCHAR(254), email_verified_at DATETIME)"
                ))
                connection.execute(text(
                    "INSERT INTO users (id, username, email, email_verified_at) VALUES "
                    "(1, 'verified', 'verified@example.edu', '2026-01-01 00:00:00'), "
                    "(2, 'pending', 'pending@example.edu', NULL)"
                ))
            ensure_schema(legacy)
            with legacy.connect() as connection:
                rows = connection.execute(text(
                    "SELECT id, is_email_verified FROM users ORDER BY id"
                )).all()
                self.assertEqual([(row.id, bool(row.is_email_verified)) for row in rows], [(1, True), (2, False)])
                self.assertEqual(connection.execute(text("SELECT count(*) FROM users")).scalar_one(), 2)
        finally:
            legacy.dispose()

    def test_registration_schema_adds_normalized_uniqueness_without_rewriting_users(self):
        legacy = create_engine("sqlite://")
        try:
            with legacy.begin() as connection:
                connection.execute(text(
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(120), "
                    "email VARCHAR(254), usn VARCHAR(64), last_name VARCHAR(80), email_verified_at DATETIME)"
                ))
                connection.execute(text(
                    "INSERT INTO users (id, username, email, usn, last_name, email_verified_at) VALUES "
                    "(1, 'old-user', 'Legacy@College.edu', 'legacy-usn', 'Legacy Name', NULL)"
                ))
            ensure_schema(legacy)
            columns = {column["name"] for column in inspect(legacy).get_columns("users")}
            self.assertTrue({"first_name", "last_name", "second_name", "account_type", "updated_at"} <= columns)
            with legacy.connect() as connection:
                indexes = set(connection.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='users'"
                )).scalars())
            self.assertIn("uq_users_email_normalized", indexes)
            self.assertIn("uq_users_student_usn_normalized", indexes)
            with legacy.connect() as connection:
                row = connection.execute(text("SELECT email, account_type, last_name, second_name FROM users WHERE id=1")).one()
                self.assertEqual((row.email, row.account_type, row.last_name, row.second_name), ("Legacy@College.edu", None, "Legacy Name", "Legacy Name"))
            with legacy.begin() as connection:
                connection.execute(text(
                    "INSERT INTO users (username, email, account_type, usn) "
                    "VALUES ('student', 'student@gmail.com', 'student', 'USN123')"
                ))
            with self.assertRaises(IntegrityError):
                with legacy.begin() as connection:
                    connection.execute(text(
                        "INSERT INTO users (username, email, account_type, usn) "
                        "VALUES ('other-student', 'other@gmail.com', 'student', 'usn123')"
                    ))
            with self.assertRaises(IntegrityError):
                with legacy.begin() as connection:
                    connection.execute(text(
                        "INSERT INTO users (username, email, account_type, usn) "
                        "VALUES ('bad-student', 'bad@gmail.com', 'student', NULL)"
                    ))
        finally:
            legacy.dispose()


if __name__ == "__main__":
    unittest.main()
