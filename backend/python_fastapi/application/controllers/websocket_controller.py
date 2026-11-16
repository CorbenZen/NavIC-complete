"""WebSocket controller: select the live-location endpoint implementation."""

from __future__ import annotations

from backend.python_asyncio.websocket.service import locations
from backend.python_fastapi.application.controllers.base import Controller


class WebSocketController(Controller):
    operations = {
        "/ws/locations": locations,
    }


__all__ = ["WebSocketController"]
