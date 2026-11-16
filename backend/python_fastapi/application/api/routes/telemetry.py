"""Telemetry read routes: latest positions and device history."""

from __future__ import annotations

from fastapi import APIRouter

from backend.python_fastapi.application.api.routes._composition import build_api_group
from backend.python_fastapi.application.controllers.telemetry_controller import (
    TelemetryController,
)

CONTROLLER = TelemetryController()


def owns(path: str) -> bool:
    if path.startswith("/api/tracking"):
        return True
    if path == "/buses/{bus_id}/history":
        return True
    return path.startswith("/api/devices/") and path.endswith("/telemetry/latest")


def build_router(source_routes) -> APIRouter:
    return build_api_group(source_routes, owns, CONTROLLER)


__all__ = ["build_router", "owns"]
