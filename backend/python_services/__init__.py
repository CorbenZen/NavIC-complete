"""Backend service layer (lazy package exports)."""

from __future__ import annotations

from backend.python_fastapi.application._lazy import make_getattr

__all__ = [
    "alert_service",
    "auth_service",
    "email_service",
    "fleet_service",
    "telemetry_service",
]

_EXPORTS = {
    "alert_service": ("backend.python_services.alert_service", "__name__"),
    "auth_service": ("backend.python_services.auth_service", "__name__"),
    "email_service": ("backend.python_services.email_service", "__name__"),
    "fleet_service": ("backend.python_services.fleet_service", "__name__"),
    "telemetry_service": ("backend.python_services.telemetry_service", "__name__"),
}

__getattr__ = make_getattr(__name__, _EXPORTS)
