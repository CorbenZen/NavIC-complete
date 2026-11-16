"""User profile, preferences and student-service routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend.python_fastapi.application.api.routes._composition import build_api_group
from backend.python_fastapi.application.controllers.user_controller import (
    UserController,
)

CONTROLLER = UserController()

PREFIXES = (
    "/api/user",
    "/api/users",
    "/api/feedback",
    "/api/support",
    "/api/bus-pass",
    "/api/admin/bus-passes",
)


def owns(path: str) -> bool:
    return path.startswith(PREFIXES)


def build_router(source_routes) -> APIRouter:
    return build_api_group(source_routes, owns, CONTROLLER)


__all__ = ["build_router", "owns"]
