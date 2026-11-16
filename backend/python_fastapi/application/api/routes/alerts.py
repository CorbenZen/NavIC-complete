"""Alert routes: system alerts."""

from __future__ import annotations

from fastapi import APIRouter

from backend.python_fastapi.application.api.routes._composition import build_api_group
from backend.python_fastapi.application.controllers.alert_controller import (
    AlertController,
)

CONTROLLER = AlertController()

PREFIXES = (
    "/alerts",
    "/api/alerts",
)


def owns(path: str) -> bool:
    return path.startswith(PREFIXES)


def build_router(source_routes) -> APIRouter:
    return build_api_group(source_routes, owns, CONTROLLER)


__all__ = ["build_router", "owns"]
