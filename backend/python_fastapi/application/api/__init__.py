"""API composition package.

Registers the domain routers, the WebSocket router, static mounts and finally
the system/SPA router (whose catch-all must be last).
"""

from __future__ import annotations

from fastapi import FastAPI

from backend.python_fastapi.application.api.routes import (
    GROUP_ORDER,
    build_routers,
    collect_mounts,
)


def register_routes(app: FastAPI, source_routes) -> None:
    """Mount every domain router and preserve the original route surface."""
    routers = build_routers(source_routes)
    for name in GROUP_ORDER:
        app.include_router(routers[name])
    for mount in collect_mounts(source_routes):
        app.mount(mount.path, app=mount.app, name=mount.name)
    app.include_router(routers["system"])


__all__ = ["register_routes"]
