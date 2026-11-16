"""Security helpers used by the backend service layer.

The cryptographic primitives are the existing, tested implementations in
``navic_tcp.security``.  This module adds backend-level token helpers that use
the same signing secret and TTL as the shared FastAPI application.
"""

from __future__ import annotations

from navic_tcp.security import (
    LoginRateLimiter,
    SlidingWindowRateLimiter,
    hash_password,
    issue_token,
    new_secret,
    password_needs_rehash,
    token_hash,
    verify_password,
    verify_token,
)


def issue_access_token(username: str, ttl_seconds: int | None = None) -> str:
    """Issue a signed bearer token using the application signing secret."""
    from navic_tcp.fastapi_app import JWT_TTL_SECONDS, SECRET

    return issue_token(SECRET, username, ttl_seconds or JWT_TTL_SECONDS)


def verify_access_token(token: str) -> dict:
    """Verify a bearer token and return its claims.

    Raises :class:`navic_tcp.security.TokenError`-compatible ``ValueError`` on
    an invalid or expired token (the shared implementation raises ``ValueError``
    subclasses).
    """
    from navic_tcp.fastapi_app import SECRET

    return verify_token(SECRET, token)


__all__ = [
    "LoginRateLimiter",
    "SlidingWindowRateLimiter",
    "hash_password",
    "issue_access_token",
    "new_secret",
    "password_needs_rehash",
    "token_hash",
    "verify_access_token",
    "verify_password",
    "verify_token",
]
