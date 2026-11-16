"""Fleet routes: vehicles, drivers, routes, geofences, devices, reports."""

from __future__ import annotations

from fastapi import APIRouter

from backend.python_fastapi.application.api.routes._composition import build_api_group
from backend.python_fastapi.application.controllers.fleet_controller import (
    FleetController,
)

CONTROLLER = FleetController()

PREFIXES = (
    "/buses",
    "/api/vehicles",
    "/devices",
    "/api/devices",
    "/drivers",
    "/api/drivers",
    "/routes",
    "/api/routes",
    "/geofences",
    "/api/geofences",
    "/settings",
    "/trips",
    "/api/dashboard",
    "/api/reports",
    "/api/audit",
)

# Paths handled by the telemetry router instead.
_TELEMETRY_PATHS = {"/buses/{bus_id}/history", "/api/tracking/latest"}


def owns(path: str) -> bool:
    if path in _TELEMETRY_PATHS:
        return False
    if path.startswith("/api/devices/") and path.endswith("/telemetry/latest"):
        return False
    return path.startswith(PREFIXES)


def build_router(source_routes) -> APIRouter:
    return build_api_group(source_routes, owns, CONTROLLER)


__all__ = ["build_router", "owns"]
