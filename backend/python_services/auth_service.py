"""Authentication service functions.

Thin, typed wrappers around the existing session/magic-link implementation in
``navic_tcp.auth``.  Keeping the cryptography and storage logic in one place
guarantees the API, WebSocket and TCP application share a single auth model.
"""

from __future__ import annotations

import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from navic_tcp import auth as _auth
from navic_tcp.models import AuthSession, MagicLinkToken, User
from navic_tcp.security import token_hash


def email_verification_expire_minutes() -> int:
    try:
        return max(5, min(1440, int(os.getenv("EMAIL_VERIFICATION_EXPIRE_MINUTES", "30"))))
    except ValueError:
        return 30


def is_email_verified(user: User) -> bool:
    """Honor the new flag and the pre-existing verified timestamp."""
    return bool(user.is_email_verified or user.email_verified_at)


def create_email_verification(db: Session, user: User) -> tuple[str, datetime]:
    """Persist a hash for a new one-time verification token; return raw token once."""
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=email_verification_expire_minutes())
    user.is_email_verified = False
    user.email_verification_token_hash = token_hash(raw_token)
    user.email_verification_expires_at = expires_at
    user.email_verification_sent_at = now
    db.flush()
    return raw_token, expires_at


def email_verification_link(raw_token: str) -> str:
    from urllib.parse import quote, urlsplit

    base_url = _auth.frontend_base_url()
    if not _auth.is_development() and urlsplit(base_url).scheme != "https":
        raise ValueError("FRONTEND_URL must use HTTPS outside development")
    return f"{base_url}/auth/verify-email?token={quote(raw_token, safe='')}"


def verify_email_token(db: Session, raw_token: str) -> User | None:
    """Atomically consume a valid token and mark its account verified."""
    if not raw_token or len(raw_token) > 512:
        return None
    digest = token_hash(raw_token)
    user = db.scalar(select(User).where(User.email_verification_token_hash == digest))
    if user is None or not hmac.compare_digest(user.email_verification_token_hash or "", digest):
        return None
    now = datetime.now(timezone.utc)
    expires_at = _auth.as_utc(user.email_verification_expires_at)
    if expires_at is None or expires_at <= now:
        user.email_verification_token_hash = None
        user.email_verification_expires_at = None
        db.commit()
        return None
    result = db.execute(
        update(User)
        .where(
            User.id == user.id,
            User.email_verification_token_hash == digest,
            User.is_email_verified.is_(False),
        )
        .values(
            is_email_verified=True,
            email_verified_at=now,
            email_verification_token_hash=None,
            email_verification_expires_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        return None
    db.commit()
    return db.get(User, user.id)


def normalize_email(value: str) -> str:
    return _auth.normalize_email(value)


def valid_email(value: str) -> bool:
    return _auth.valid_email(value)


def is_development() -> bool:
    return _auth.is_development()


def magic_link_ttl_minutes() -> int:
    return _auth.magic_link_ttl_minutes()


def session_ttl_minutes() -> int:
    return _auth.session_ttl_minutes()


def create_magic_link(
    db: Session, user: User, request=None
) -> tuple[MagicLinkToken, str]:
    """Create a single-use magic-link token and return ``(row, raw_token)``."""
    return _auth.create_magic_link(db, user, request)


def verify_magic_link(db: Session, raw_token: str) -> User | None:
    """Consume a magic-link token and return its user, or ``None``."""
    return _auth.verify_magic_link(db, raw_token)


def create_session(
    db: Session, user: User, request=None
) -> tuple[str, str, AuthSession]:
    """Create a database-backed session and return ``(token, csrf, row)``."""
    return _auth.create_session(db, user, request)


def resolve_session(db: Session, raw_token: str | None) -> tuple[dict, AuthSession] | None:
    """Resolve a session cookie to ``(principal, session_row)``."""
    return _auth.resolve_session(db, raw_token)


def revoke_session(db: Session, raw_token: str | None) -> bool:
    return _auth.revoke_session(db, raw_token)


def csrf_matches(session: AuthSession, header_value: str | None) -> bool:
    return _auth.csrf_matches(session, header_value)


def set_session_cookies(response, raw_session: str, raw_csrf: str) -> None:
    _auth.set_session_cookies(response, raw_session, raw_csrf)


def clear_session_cookies(response) -> None:
    _auth.clear_session_cookies(response)


def cookie_settings(max_age: int) -> dict:
    return _auth.cookie_settings(max_age)


def frontend_base_url() -> str:
    return _auth.frontend_base_url()


def build_verify_link(raw_token: str) -> str:
    return _auth.build_verify_link(raw_token)


def session_expiry(minutes: int | None = None) -> datetime:
    from datetime import timedelta

    from backend.python_utils.helpers import utc_now

    return utc_now() + timedelta(minutes=minutes or session_ttl_minutes())


__all__ = [
    "build_verify_link",
    "clear_session_cookies",
    "cookie_settings",
    "create_magic_link",
    "create_session",
    "csrf_matches",
    "frontend_base_url",
    "is_development",
    "magic_link_ttl_minutes",
    "normalize_email",
    "resolve_session",
    "revoke_session",
    "session_expiry",
    "session_ttl_minutes",
    "set_session_cookies",
    "valid_email",
    "verify_magic_link",
]
