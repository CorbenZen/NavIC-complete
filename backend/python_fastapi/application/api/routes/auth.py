"""Authentication routes.

The shared ``navic_tcp`` application keeps its legacy email/password, magic-link,
Google OIDC and administrator routes.  The modular backend additionally exposes
the primary User ID + password contract under ``/api/auth`` and ``/auth``.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.python_fastapi.application.api.routes._composition import build_api_group
from backend.python_fastapi.application.controllers.auth_controller import (
    AuthController,
    id_login,
    logout,
    me,
    register_account,
    resend_verification,
    verification_status,
    verify_email,
)

CONTROLLER = AuthController()


def owns(path: str) -> bool:
    return path.startswith("/auth/")


def build_router(source_routes) -> APIRouter:
    router = build_api_group(source_routes, owns, CONTROLLER)

    # Primary ID + password flow (no email address or verification mail).
    router.add_api_route("/api/auth/register", register_account, methods=["POST"], status_code=201, name="api_register")
    router.add_api_route("/api/auth/login", id_login, methods=["POST"], name="api_login")
    router.add_api_route("/api/auth/logout", logout, methods=["POST"], name="api_logout")
    router.add_api_route("/api/auth/me", me, methods=["GET"], name="api_me")
    # Short aliases used by the SPA and by clients that omit the /api prefix.
    router.add_api_route("/auth/register", register_account, methods=["POST"], status_code=201, name="register")
    router.add_api_route("/auth/login/id", id_login, methods=["POST"], name="id_login")

    # Legacy email-verification and magic-link support for existing accounts.
    router.add_api_route("/auth/verify-email", verify_email, methods=["POST"], name="verify_email")
    router.add_api_route(
        "/auth/resend-verification",
        resend_verification,
        methods=["POST"],
        status_code=202,
        name="resend_verification",
    )
    router.add_api_route(
        "/auth/verification-status",
        verification_status,
        methods=["GET"],
        name="verification_status",
    )
    router.add_api_route("/api/auth/verify-email", verify_email, methods=["POST"], name="api_verify_email")
    router.add_api_route(
        "/api/auth/resend-verification",
        resend_verification,
        methods=["POST"],
        status_code=202,
        name="api_resend_verification",
    )
    router.add_api_route(
        "/api/auth/verification-status",
        verification_status,
        methods=["GET"],
        name="api_verification_status",
    )
    return router


__all__ = ["build_router", "owns"]
