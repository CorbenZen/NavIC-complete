"""Idempotent, additive schema management.

The project supports both a fresh database (created from SQLAlchemy metadata) and
older development databases created before recent columns existed.  Every change
here is additive: records are never deleted, and existing user values are only
copied into a newly added nullable compatibility field when that field is empty.
"""

from __future__ import annotations

from contextlib import suppress

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .db import Base, engine


def _add_column(bind: Engine, table: str, name: str, sql_type: str) -> bool:
    columns = {column["name"] for column in inspect(bind).get_columns(table)}
    if name in columns:
        return False
    with bind.begin() as connection:
        connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {sql_type}'))
    return True


def ensure_schema(bind: Engine = engine) -> None:
    """Create missing tables and add missing nullable columns.

    Importing ``navic_tcp.models`` registers every table on ``Base.metadata``.
    ``create_all`` is check-first, so it is safe to run on every startup.
    """

    # Importing the models registers their tables on Base.metadata.
    from . import models

    Base.metadata.create_all(bind=bind)
    tables = set(inspect(bind).get_table_names())
    is_postgres = bind.dialect.name == "postgresql"
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if is_postgres else "DATETIME"

    if "location_history" in tables:
        for name, sql_type in {
            "altitude_m": "FLOAT",
            "fix_valid": "BOOLEAN",
            "satellites_in_view": "INTEGER",
            "satellites_used": "INTEGER",
            "pdop": "FLOAT",
            "hdop": "FLOAT",
            "vdop": "FLOAT",
            "gnss_metadata": "JSON",
            "ignition": "BOOLEAN",
            "odometer": "FLOAT",
            "data_source": "VARCHAR(24) DEFAULT 'hardware'",
        }.items():
            _add_column(bind, "location_history", name, sql_type)
        columns = {column["name"] for column in inspect(bind).get_columns("location_history")}
        if "simulated" in columns:
            with bind.begin() as connection:
                # Backfill provenance only where the column is still empty. Never
                # relabel an explicit value.
                connection.execute(text(
                    "UPDATE location_history SET data_source = CASE "
                    "WHEN simulated = TRUE THEN 'simulator' ELSE 'hardware' END "
                    "WHERE data_source IS NULL OR trim(data_source) = ''"
                    if is_postgres else
                    "UPDATE location_history SET data_source = CASE "
                    "WHEN simulated = 1 THEN 'simulator' ELSE 'hardware' END "
                    "WHERE data_source IS NULL OR trim(data_source) = ''"
                ))

    if "buses" in tables:
        _add_column(
            bind,
            "buses",
            "route_id",
            "INTEGER REFERENCES routes(id) ON DELETE SET NULL",
        )
        _add_column(bind, "buses", "created_at", timestamp_type)

    if "tracking_devices" in tables:
        _add_column(bind, "tracking_devices", "active", "BOOLEAN DEFAULT TRUE" if is_postgres else "BOOLEAN DEFAULT 1")
        _add_column(bind, "tracking_devices", "created_at", timestamp_type)
        with bind.begin() as connection:
            connection.execute(
                text(
                    "UPDATE tracking_devices SET active = TRUE WHERE active IS NULL"
                    if is_postgres
                    else "UPDATE tracking_devices SET active = 1 WHERE active IS NULL"
                )
            )

    if "drivers" in tables:
        _add_column(bind, "drivers", "email", "VARCHAR(254)")
        _add_column(bind, "drivers", "active", "BOOLEAN DEFAULT TRUE" if is_postgres else "BOOLEAN DEFAULT 1")
        _add_column(bind, "drivers", "created_at", timestamp_type)
        with bind.begin() as connection:
            # Backfill only where an old nullable column left gaps.
            connection.execute(text("UPDATE drivers SET active = TRUE WHERE active IS NULL" if is_postgres else "UPDATE drivers SET active = 1 WHERE active IS NULL"))

    if "routes" in tables:
        _add_column(bind, "routes", "stops", "JSON")
        _add_column(bind, "routes", "color", "VARCHAR(16) DEFAULT '#0f766e'")
        _add_column(bind, "routes", "created_at", timestamp_type)

    if "geofences" in tables:
        _add_column(bind, "geofences", "created_at", timestamp_type)

    if "users" in tables:
        _add_column(bind, "users", "created_at", timestamp_type)
        _add_column(bind, "users", "updated_at", timestamp_type)
        _add_column(bind, "users", "first_name", "VARCHAR(80)")
        _add_column(bind, "users", "last_name", "VARCHAR(80)")
        added_second_name = _add_column(bind, "users", "second_name", "VARCHAR(80)")
        # Older consumers use last_name; copy it once when the additive field
        # is first introduced so legacy accounts display the same name.
        if added_second_name:
            with bind.begin() as connection:
                connection.execute(
                    text("UPDATE users SET second_name = last_name WHERE second_name IS NULL")
                )
        _add_column(bind, "users", "account_type", "VARCHAR(16)")
        _add_column(bind, "users", "email_verified_at", timestamp_type)
        _add_column(bind, "users", "is_email_verified", "BOOLEAN NOT NULL DEFAULT FALSE" if is_postgres else "BOOLEAN NOT NULL DEFAULT 0")
        _add_column(bind, "users", "email_verification_token_hash", "VARCHAR(64)")
        _add_column(bind, "users", "email_verification_expires_at", timestamp_type)
        _add_column(bind, "users", "email_verification_sent_at", timestamp_type)
        _add_column(bind, "users", "last_login_at", timestamp_type)
        _add_column(bind, "users", "full_name", "VARCHAR(200)")
        _add_column(bind, "users", "avatar_url", "VARCHAR(1024)")
        _add_column(bind, "users", "phone", "VARCHAR(32)")
        _add_column(bind, "users", "department", "VARCHAR(120)")
        _add_column(bind, "users", "usn", "VARCHAR(64)")
        _add_column(bind, "users", "user_id", "VARCHAR(64)")
        _add_column(bind, "users", "is_profile_complete", "BOOLEAN DEFAULT TRUE" if is_postgres else "BOOLEAN DEFAULT 1")
        with bind.begin() as connection:
            # Existing accounts are trusted only when the prior schema already
            # recorded a completed email verification (including verified OAuth
            # and administrator accounts). Unverified rows remain unverified.
            connection.execute(text(
                "UPDATE users SET is_email_verified = TRUE "
                "WHERE email_verified_at IS NOT NULL AND is_email_verified = FALSE"
                if is_postgres else
                "UPDATE users SET is_email_verified = 1 "
                "WHERE email_verified_at IS NOT NULL AND is_email_verified = 0"
            ))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_users_email_verification_token_hash ON users (email_verification_token_hash)"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_normalized ON users (lower(trim(email)))"))
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_user_id_normalized ON users (lower(trim(user_id)))"
            ))
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_student_usn_normalized "
                "ON users (lower(trim(usn))) WHERE account_type = 'student' AND usn IS NOT NULL"
            ))
            connection.execute(text(
                "UPDATE users SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP) "
                "WHERE updated_at IS NULL"
            ))
            connection.execute(text(
                "UPDATE users SET user_id = upper('USER' || id) "
                "WHERE user_id IS NULL OR trim(user_id) = ''"
            ))
            if not is_postgres:
                for event in ("INSERT", "UPDATE"):
                    suffix = event.lower()
                    for check, condition, message in (
                        ("account_type", "NEW.account_type IS NOT NULL AND NEW.account_type NOT IN ('student', 'teacher')", "invalid account type"),
                        ("student_usn", "NEW.account_type = 'student' AND (NEW.usn IS NULL OR trim(NEW.usn) = '')", "student USN required"),
                        ("teacher_usn", "NEW.account_type = 'teacher' AND NEW.usn IS NOT NULL", "teacher USN must be null"),
                    ):
                        connection.execute(text(
                            f"CREATE TRIGGER IF NOT EXISTS trg_users_{check}_{suffix} "
                            f"BEFORE {event} ON users WHEN {condition} "
                            f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
                        ))

    # Foreign keys are opt-in in SQLite. Enabling them per connection is done in
    # db.py; this index keeps latest-per-device queries fast on both engines.
    with bind.begin() as connection:
        with suppress(Exception):
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_location_device_time "
                    "ON location_history (device_id, timestamp)"
                )
            )


# Backwards-compatible names used by earlier startup code/tests.
def ensure_gnss_schema(bind: Engine = engine) -> None:
    ensure_schema(bind)


def ensure_bus_route_schema(bind: Engine = engine) -> None:
    ensure_schema(bind)
