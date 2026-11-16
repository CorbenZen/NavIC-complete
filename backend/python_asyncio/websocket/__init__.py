"""WebSocket package: connection manager and live location endpoint."""

from backend.python_asyncio.websocket.manager import WebSocketManager, manager
from backend.python_asyncio.websocket.service import locations

__all__ = ["WebSocketManager", "locations", "manager"]
