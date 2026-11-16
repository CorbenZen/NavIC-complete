"""Live location WebSocket route."""

from __future__ import annotations

from fastapi import APIRouter

from backend.python_fastapi.application.api.routes._composition import (
    build_websocket_router,
)
from backend.python_fastapi.application.controllers.websocket_controller import (
    WebSocketController,
)

CONTROLLER = WebSocketController()


def build_router(source_routes) -> APIRouter:
    return build_websocket_router(source_routes, CONTROLLER)


__all__ = ["build_router"]
