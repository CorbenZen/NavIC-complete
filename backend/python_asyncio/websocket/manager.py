"""WebSocket connection manager.

The manager is a thin, typed facade over the shared in-process hub.  Telemetry
publishers in ``navic_tcp`` and this backend therefore broadcast to the
same live clients; the manager only centralises connection bookkeeping for the
modular application.
"""

from __future__ import annotations

from typing import Any

from fastapi import WebSocket

from navic_tcp import fastapi_app as shared


class WebSocketManager:
    @property
    def count(self) -> int:
        return shared.hub.count

    async def connect(self, websocket: WebSocket, *, is_admin: bool = False) -> None:
        await shared.hub.connect(websocket, is_admin=is_admin)

    def disconnect(self, websocket: WebSocket) -> None:
        shared.hub.disconnect(websocket)

    async def publish(self, message: dict[str, Any]) -> None:
        await shared.hub.publish(message)

    async def publish_admin(self, message: dict[str, Any]) -> None:
        await shared.hub.publish_admin(message)


manager = WebSocketManager()

__all__ = ["WebSocketManager", "manager"]
