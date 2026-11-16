"""FastAPI dependencies shared by backend routers and services.

The authentication dependencies are the existing, tested implementations from
``navic_tcp.fastapi_app``.  Re-exporting them keeps one authorisation model for
the TCP application and the website while exposing a clean backend import path.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from backend.python_fastapi.application.core.config import Settings, get_settings
from backend.python_sqlalchemy.database.session import SessionLocal
from navic_tcp.fastapi_app import admin_user, current_user, management_user


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_app_settings() -> Settings:
    """Inject the cached backend settings."""
    return get_settings()


# Convenience alias for routers that prefer the ``Depends(get_db)`` spelling.
DatabaseSession = Depends(get_db)


__all__ = [
    "DatabaseSession",
    "admin_user",
    "current_user",
    "get_app_settings",
    "get_db",
    "management_user",
]
