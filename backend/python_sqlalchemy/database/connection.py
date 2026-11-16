"""Database engine, URL resolution and connectivity helpers."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from navic_tcp.db import DATABASE_URL, engine
from navic_tcp.schema import (
    ensure_bus_route_schema,
    ensure_gnss_schema,
    ensure_schema,
)


def init_database(bind: Engine = engine) -> Engine:
    """Create missing tables and apply additive schema upgrades."""
    ensure_schema(bind)
    return bind


def database_reachable(bind: Engine = engine) -> bool:
    """Return ``True`` when a trivial ``SELECT 1`` succeeds."""
    try:
        with bind.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


__all__ = [
    "DATABASE_URL",
    "database_reachable",
    "engine",
    "ensure_bus_route_schema",
    "ensure_gnss_schema",
    "ensure_schema",
    "init_database",
]
