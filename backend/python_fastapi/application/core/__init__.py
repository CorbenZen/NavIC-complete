"""Backend core package: configuration, security and dependencies."""

from __future__ import annotations

from backend.python_fastapi.application._lazy import make_getattr

__all__ = [
    "Settings",
    "admin_user",
    "current_user",
    "get_app_settings",
    "get_db",
    "get_settings",
    "load_environment",
    "management_user",
]

_EXPORTS = {
    "Settings": ("backend.python_fastapi.application.core.config", "Settings"),
    "get_settings": ("backend.python_fastapi.application.core.config", "get_settings"),
    "load_environment": ("backend.python_fastapi.application.core.config", "load_environment"),
    "get_db": ("backend.python_fastapi.application.core.dependencies", "get_db"),
    "get_app_settings": ("backend.python_fastapi.application.core.dependencies", "get_app_settings"),
    "current_user": ("backend.python_fastapi.application.core.dependencies", "current_user"),
    "management_user": ("backend.python_fastapi.application.core.dependencies", "management_user"),
    "admin_user": ("backend.python_fastapi.application.core.dependencies", "admin_user"),
}

__getattr__ = make_getattr(__name__, _EXPORTS)
