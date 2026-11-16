"""SQLAlchemy engine/session configuration."""
import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .local_paths import default_database_url, ensure_sqlite_parent, prepare_local_database


class Base(DeclarativeBase):
    pass


def normalize_database_url(value: str) -> str:
    """Select the installed Psycopg 3 driver for common managed PG URLs."""
    value = value.strip()
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", default_database_url()))

# On first local launch, preserve the previous repository-local SQLite file by
# taking a consistent snapshot into the persistent user data directory. Never
# overwrite an existing database and never remove the original file.
prepare_local_database(DATABASE_URL, Path(__file__).resolve().parents[1] / "navic_dev.db")
ensure_sqlite_parent(DATABASE_URL)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
