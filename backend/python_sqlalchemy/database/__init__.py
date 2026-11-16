"""Database package: engine, sessions, schema initialisation and seeding."""

from __future__ import annotations

from backend.python_fastapi.application._lazy import make_getattr

__all__ = [
    "DATABASE_URL",
    "Base",
    "SessionLocal",
    "database_reachable",
    "engine",
    "ensure_bus_route_schema",
    "ensure_gnss_schema",
    "ensure_schema",
    "get_db",
    "init_database",
    "session_scope",
]

_EXPORTS = {
    "Base": ("backend.python_sqlalchemy.database.base", "Base"),
    "DATABASE_URL": ("backend.python_sqlalchemy.database.connection", "DATABASE_URL"),
    "engine": ("backend.python_sqlalchemy.database.connection", "engine"),
    "database_reachable": ("backend.python_sqlalchemy.database.connection", "database_reachable"),
    "ensure_bus_route_schema": ("backend.python_sqlalchemy.database.connection", "ensure_bus_route_schema"),
    "ensure_gnss_schema": ("backend.python_sqlalchemy.database.connection", "ensure_gnss_schema"),
    "ensure_schema": ("backend.python_sqlalchemy.database.connection", "ensure_schema"),
    "init_database": ("backend.python_sqlalchemy.database.connection", "init_database"),
    "SessionLocal": ("backend.python_sqlalchemy.database.session", "SessionLocal"),
    "get_db": ("backend.python_sqlalchemy.database.session", "get_db"),
    "session_scope": ("backend.python_sqlalchemy.database.session", "session_scope"),
}

__getattr__ = make_getattr(__name__, _EXPORTS)
