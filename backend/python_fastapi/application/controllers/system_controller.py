"""System controller: health, metadata and database reachability."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.python_fastapi.application.controllers.base import Controller
from backend.python_fastapi.application.core.config import get_settings
from backend.python_sqlalchemy.database.connection import database_reachable
from navic_tcp import fastapi_app as shared


def health(request: Request) -> JSONResponse:
    """Return the same health contract as the shared application.

    The modular lifespan mirrors the embedded TCP receiver onto this app's
    state, so the URL served by ``backend.python_fastapi.application.main`` reports the real receiver
    status rather than a placeholder.
    """
    database = "ok" if database_reachable() else "error"
    tcp = "disabled"
    receiver = getattr(request.app.state, "tcp", None)
    if receiver is not None:
        tcp = "listening" if getattr(receiver, "_server", None) is not None else "stopped"
    payload = {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "tcp": tcp,
        "environment": shared.APP_ENV,
        "version": shared.app.version,
        "websocket_clients": shared.hub.count,
    }
    return JSONResponse(status_code=200 if database == "ok" else 503, content=payload)


class SystemController(Controller):
    operations = {
        "/health": health,
    }

    def __init__(self) -> None:
        self.settings = get_settings()


__all__ = ["SystemController", "health"]
