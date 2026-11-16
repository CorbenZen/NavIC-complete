"""System routes: health, metadata and same-origin SPA serving.

The catch-all SPA route must be registered after every API route and static
mount, so this router is included last by :func:`backend.python_fastapi.application.api.register_routes`.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.python_fastapi.application.api.routes._composition import build_api_group
from backend.python_fastapi.application.controllers.system_controller import (
    SystemController,
)

CONTROLLER = SystemController()

PATHS = {
    "/health",
    "/api/meta",
    "/api/admin/demo/simulation/start",
    "/api/admin/demo/simulation/stop",
    "/api/admin/demo/simulation/state",
    "/{full_path:path}",
}


def owns(path: str) -> bool:
    return path in PATHS or path.startswith("/{full_path:")


def build_router(source_routes) -> APIRouter:
    return build_api_group(source_routes, owns, CONTROLLER)


__all__ = ["build_router", "owns"]
