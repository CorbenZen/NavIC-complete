"""ASGI application entry point for the NavIC website backend.

The domain implementation (models, authentication, telemetry pipeline and the
path-operation bodies) lives in the independent ``navic_tcp`` package.  This
module composes those routes into a modular FastAPI application, applies the
backend configuration and exposes the stable ``backend.python_fastapi.application.main:app`` target.
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

from backend.python_fastapi.application.core.config import (
    get_settings,
    load_environment,
)

# The shared modules read several settings at import time, so load ``.env`` and
# publish defaults before importing anything that touches ``navic_tcp``.
load_environment()
SETTINGS = get_settings()
SETTINGS.apply_defaults()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from backend.python_fastapi.application.api import register_routes
from navic_tcp import fastapi_app as shared

LOG = logging.getLogger("navic.backend")


@asynccontextmanager
async def backend_lifespan(app: FastAPI):
    """Run the shared startup/shutdown lifecycle against the shared app.

    The shared health endpoint inspects ``navic_tcp.fastapi_app.app.state`` for
    the embedded TCP receiver, so the lifecycle is executed on that app object
    while this modular app serves HTTP and WebSocket traffic.
    """
    SETTINGS.validate_production()
    async with shared.lifespan(shared.app):
        app.state.started_at = getattr(shared.app.state, "started_at", None)
        if hasattr(shared.app.state, "tcp"):
            app.state.tcp = shared.app.state.tcp
        if hasattr(shared.app.state, "demo_simulation"):
            app.state.demo_simulation = shared.app.state.demo_simulation
        yield


def create_application() -> FastAPI:
    """Build the modular FastAPI application."""
    app = FastAPI(
        title=shared.app.title,
        version=shared.app.version,
        description=shared.app.description,
        lifespan=backend_lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    register_routes(app, shared.app.routes)

    # Reuse the shared CORS and CSRF middleware unchanged.
    app.user_middleware = list(shared.app.user_middleware)
    app.exception_handlers.update(shared.app.exception_handlers)
    app.dependency_overrides.update(shared.app.dependency_overrides)

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        reference_id = secrets.token_hex(4)
        LOG.exception("database error ref=%s while handling %s %s", reference_id, request.method, request.url.path)
        return JSONResponse(
            status_code=503,
            content={"detail": "database operation failed", "reference_id": reference_id},
            headers={"X-Error-Reference": reference_id},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # Keep traceback details in the server log and give support a short id to correlate safely.
        reference_id = secrets.token_hex(4)
        LOG.exception("unhandled error ref=%s while handling %s %s", reference_id, request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "internal server error", "reference_id": reference_id},
            headers={"X-Error-Reference": reference_id},
        )

    # Build the middleware stack once, after handlers and middleware are final.
    app.middleware_stack = app.build_middleware_stack()
    app.state.settings = SETTINGS
    app.state.shared_app = shared.app
    return app


app = create_application()

__all__ = ["app", "backend_lifespan", "create_application"]
