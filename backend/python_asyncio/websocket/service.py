"""WebSocket endpoint implementation for live fleet locations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import Query, WebSocket, WebSocketDisconnect

from backend.python_asyncio.websocket.manager import manager
from backend.python_sqlalchemy.database.session import SessionLocal
from navic_tcp import auth as auth_service
from navic_tcp import fastapi_app as shared
from navic_tcp.fastapi_app import _user_from_token

LOG = logging.getLogger("navic.backend.websocket")


def _principal(token: str | None, websocket: WebSocket):
    """Resolve a token or the browser session cookie, mirroring REST auth."""
    principal = None
    bearer = websocket.headers.get("authorization", "")
    if not token and bearer.lower().startswith("bearer "):
        token = bearer[7:]
    if token:
        try:
            principal = _user_from_token(token)
        except ValueError:
            principal = None
    if principal is None:
        session_cookie = websocket.cookies.get(auth_service.SESSION_COOKIE)
        if session_cookie:
            with SessionLocal() as db:
                resolved = auth_service.resolve_session(db, session_cookie)
                principal = resolved[0] if resolved is not None else None
    if shared.DEMO_AUTH_BYPASS:
        principal = {"role": "admin"}
    return principal


async def locations(websocket: WebSocket, token: str | None = Query(default=None)):
    """Accept an authenticated client, answer ``ping`` and relay broadcasts."""
    principal = _principal(token, websocket)
    if principal is None:
        await websocket.close(code=4401)
        return
    await manager.connect(websocket, is_admin=principal.get("role") == "admin")
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong", "server_time": datetime.now(timezone.utc).isoformat()})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
        LOG.exception("websocket client failed")


__all__ = ["locations"]
