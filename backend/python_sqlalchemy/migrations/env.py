"""Alembic environment for the NavIC schema.

The URL and metadata come from the same modules the application uses, so a
migration cannot silently target a different database or model set.  Migrations
are additive: the application still calls ``ensure_schema`` on startup for
in-place upgrades of older development databases.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, inspect, pool, text

# Allow `alembic` to be run from either the repository root or `backend/`.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.python_fastapi.application.core.config import (
    get_settings,
    load_environment,
)

load_environment()
SETTINGS = get_settings()
SETTINGS.apply_defaults()

from navic_tcp.db import DATABASE_URL
from navic_tcp.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# `%` is the Alembic interpolation character; encoded passwords may contain it.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata
IS_SQLITE = DATABASE_URL.startswith("sqlite")


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=IS_SQLITE,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # Alembic creates this column as VARCHAR(32), but our descriptive
        # revision IDs exceed that length. PostgreSQL enforces the limit and
        # would fail while advancing the revision after a migration succeeds.
        # Create a compatible table up front, or widen the default one left by
        # an earlier Alembic run. SQLite ignores VARCHAR lengths, so its table
        # needs no alteration.
        if connection.dialect.name == "postgresql":
            if not inspect(connection).has_table("alembic_version"):
                connection.execute(
                    text(
                        "CREATE TABLE alembic_version "
                        "(version_num VARCHAR(128) NOT NULL PRIMARY KEY)"
                    )
                )
                connection.commit()
            else:
                version_column = next(
                    column
                    for column in inspect(connection).get_columns("alembic_version")
                    if column["name"] == "version_num"
                )
                if getattr(version_column["type"], "length", 0) < 128:
                    connection.execute(
                        text(
                            "ALTER TABLE alembic_version "
                            "ALTER COLUMN version_num TYPE VARCHAR(128)"
                        )
                    )
                    connection.commit()
            # SQLAlchemy 2 starts an implicit transaction for the inspector's
            # catalog query above. If the column already has the right width,
            # there is no DDL commit to close it; Alembic would then treat that
            # transaction as externally owned and roll back revision updates on
            # connection close. Leave a clean connection for Alembic to manage.
            if connection.in_transaction():
                connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=IS_SQLITE,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
