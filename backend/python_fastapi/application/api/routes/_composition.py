"""Helpers that re-home the existing path operations into domain routers.

The path-operation bodies stay in ``navic_tcp.fastapi_app``; this module copies
each route's metadata into a domain ``APIRouter`` without duplicating logic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from fastapi import APIRouter
from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import Mount

Predicate = Callable[[str], bool]


def add_api_route(router: APIRouter, route: APIRoute, endpoint=None) -> None:
    """Copy one path operation, preserving validation and OpenAPI metadata."""
    router.add_api_route(
        route.path,
        endpoint or route.endpoint,
        response_model=route.response_model,
        status_code=route.status_code,
        tags=list(route.tags),
        dependencies=list(route.dependencies),
        summary=route.summary,
        description=route.description,
        responses=route.responses,
        deprecated=route.deprecated,
        methods=sorted(route.methods),
        operation_id=route.operation_id,
        response_model_include=route.response_model_include,
        response_model_exclude=route.response_model_exclude,
        response_model_by_alias=route.response_model_by_alias,
        response_model_exclude_unset=route.response_model_exclude_unset,
        response_model_exclude_defaults=route.response_model_exclude_defaults,
        response_model_exclude_none=route.response_model_exclude_none,
        include_in_schema=route.include_in_schema,
        name=route.name,
    )


def build_api_group(source_routes: Iterable, owns: Predicate, controller=None) -> APIRouter:
    """Build a router from every ``APIRoute`` whose path matches *owns*.

    When a controller is supplied it may override an operation with a
    service-backed handler; otherwise the shared domain handler is reused.
    """
    router = APIRouter()
    for route in source_routes:
        if isinstance(route, APIRoute) and owns(route.path):
            method = min(route.methods) if route.methods else None
            endpoint = controller.resolve(route.path, method) if controller is not None else None
            add_api_route(router, route, endpoint)
    return router


def build_websocket_router(source_routes: Iterable, controller=None) -> APIRouter:
    """Build a router containing every WebSocket route."""
    router = APIRouter()
    for route in source_routes:
        if isinstance(route, APIWebSocketRoute):
            endpoint = controller.resolve(route.path) if controller is not None else None
            router.add_api_websocket_route(
                route.path,
                endpoint or route.endpoint,
                name=route.name,
                dependencies=list(route.dependencies),
            )
    return router


def collect_mounts(source_routes: Iterable) -> list[Mount]:
    """Return static-file mounts in their original registration order."""
    return [route for route in source_routes if isinstance(route, Mount)]


__all__ = [
    "add_api_route",
    "build_api_group",
    "build_websocket_router",
    "collect_mounts",
]
