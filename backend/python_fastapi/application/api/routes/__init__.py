"""Domain routers for the NavIC API.

Each module owns a path family and builds its router from the shared route
table, so there is no duplicated endpoint logic.
"""

from __future__ import annotations

from backend.python_fastapi.application.api.routes import (
    alerts,
    auth,
    fleet,
    share,
    system,
    telemetry,
    users,
    websocket,
)
from backend.python_fastapi.application.api.routes._composition import collect_mounts

GROUP_ORDER = ("auth", "users", "fleet", "telemetry", "alerts", "websocket", "share")
_MODULES = {
    "auth": auth,
    "users": users,
    "fleet": fleet,
    "telemetry": telemetry,
    "alerts": alerts,
    "websocket": websocket,
    "share": share,
}


def build_routers(source_routes) -> dict[str, object]:
    """Build every domain router plus the trailing system router."""
    routers = {
        name: module.build_router(source_routes)
        for name, module in _MODULES.items()
    }
    routers["system"] = system.build_router(source_routes)
    return routers


__all__ = ["GROUP_ORDER", "build_routers", "collect_mounts"]
