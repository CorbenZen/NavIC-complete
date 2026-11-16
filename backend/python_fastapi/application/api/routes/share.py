"""Share token and public API routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.routing import APIRoute


def build_router(source_routes):
    """Extract share/public routes from source_routes and build a router."""
    router = APIRouter()

    # Filter routes that belong to share/public API
    share_routes = [
        r for r in source_routes
        if isinstance(r, APIRoute) and r.path.startswith(("/api/buses/", "/public/bus", "/public/api/bus"))
    ]

    for route in share_routes:
        router.routes.append(route)

    return router