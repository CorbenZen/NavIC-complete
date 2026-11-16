"""Passwordless email authentication primitives.

Security properties:

* email tokens and browser session tokens are random and stored only as SHA-256
  hashes;
* email tokens are single-use and time limited;
* sessions are opaque, database-backed, revocable and delivered in HttpOnly
  cookies;
* a second readable CSRF cookie is matched against the session's stored hash for
  every unsafe same-site request.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import AuthSession, MagicLinkToken, User
from .security import new_secret, token_hash

SESSION_COOKIE = "navic_session"
CSRF_COOKIE = "navic_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLES = {"admin", "transport", "viewer"}
MANAGEMENT_ROLES = {"admin", "transport", "transport_department", "manager"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def is_development() -> bool:
    return os.getenv("APP_ENV", "production").strip().lower() in {"development", "dev", "local"}


def normalize_email(value: str) -> str:
    return value.strip().lower()


def valid_email(value: str) -> bool:
    return bool(value) and len(value) <= 254 and bool(_EMAIL.fullmatch(value))


def magic_link_ttl_minutes() -> int:
    try:
        return max(5, min(30, int(os.getenv("MAGIC_LINK_TTL_MINUTES", "15"))))
    except ValueError:
        return 15


def session_ttl_minutes() -> int:
    try:
        return max(5, min(60 * 24 * 30, int(os.getenv("SESSION_TTL_MINUTES", "720"))))
    except ValueError:
        return 720


def cookie_secure() -> bool:
    raw = os.getenv("COOKIE_SECURE")
    if raw is None:
        return not is_development()
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def cookie_samesite() -> str:
    value = os.getenv("COOKIE_SAMESITE", "lax").strip().lower()
    return value if value in {"lax", "strict", "none"} else "lax"


def frontend_base_url() -> str:
    value = (
        os.getenv("FRONTEND_URL", "").strip()
        or os.getenv("BACKEND_URL", "").strip()
        or "http://localhost:5173"
    )
    return value.rstrip("/")


def build_verify_link(raw_token: str) -> str:
    return f"{frontend_base_url()}/auth/verify?token={quote(raw_token, safe='')}"


def client_ip(request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "") if request is not None else ""
    if forwarded:
        return forwarded.split(",")[0].strip()[:80]
    return (request.client.host if request is not None and request.client else "unknown")[:80]


def _ip_hash(ip: str) -> str:
    salt = os.getenv("AUTH_IP_SALT", "").strip() or os.getenv("JWT_SECRET", "").strip()
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


def user_agent(request) -> str:
    value = request.headers.get("user-agent", "") if request is not None else ""
    return value[:300]


def create_magic_link(db: Session, user: User, request=None) -> tuple[str, datetime]:
    raw = new_secret(32)
    expires = now_utc() + timedelta(minutes=magic_link_ttl_minutes())
    # Invalidating older unused links limits the useful lifetime of leaked mail.
    db.execute(
        update(MagicLinkToken)
        .where(MagicLinkToken.user_id == user.id, MagicLinkToken.used_at.is_(None))
        .values(used_at=now_utc())
    )
    db.add(
        MagicLinkToken(
            user_id=user.id,
            token_hash=token_hash(raw),
            expires_at=expires,
            requested_ip_hash=_ip_hash(client_ip(request)),
        )
    )
    db.commit()
    return raw, expires


def verify_magic_link(db: Session, raw_token: str) -> User | None:
    if not raw_token or len(raw_token) > 512:
        return None
    digest = token_hash(raw_token)
    row = db.scalar(
        select(MagicLinkToken).where(MagicLinkToken.token_hash == digest, MagicLinkToken.used_at.is_(None))
    )
    if row is None:
        return None
    now = now_utc()
    expires = as_utc(row.expires_at)
    if expires is None or expires <= now:
        row.used_at = now
        db.commit()
        return None
    # Atomically claim the token so two concurrent verifications cannot both win.
    claimed = db.execute(
        update(MagicLinkToken)
        .where(MagicLinkToken.id == row.id, MagicLinkToken.used_at.is_(None))
        .values(used_at=now)
    )
    if claimed.rowcount != 1:
        db.rollback()
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.active:
        db.commit()
        return None
    user.email_verified_at = user.email_verified_at or now
    user.is_email_verified = True
    user.last_login_at = now
    db.commit()
    db.refresh(user)
    return user


def create_session(db: Session, user: User, request=None) -> tuple[str, str, datetime]:
    raw = new_secret(32)
    csrf = new_secret(24)
    expires = now_utc() + timedelta(minutes=session_ttl_minutes())
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=token_hash(raw),
            csrf_hash=token_hash(csrf),
            expires_at=expires,
            last_seen_at=now_utc(),
            ip_hash=_ip_hash(client_ip(request)),
            user_agent=user_agent(request),
        )
    )
    db.commit()
    return raw, csrf, expires


def resolve_session(db: Session, raw_token: str | None) -> tuple[dict, AuthSession] | None:
    if not raw_token or len(raw_token) > 512:
        return None
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_hash(raw_token),
            AuthSession.revoked_at.is_(None),
        )
    )
    if session is None:
        return None
    now = now_utc()
    expires = as_utc(session.expires_at)
    if expires is None or expires <= now:
        session.revoked_at = now
        db.commit()
        return None
    user = db.get(User, session.user_id)
    if (
        user is None
        or not user.active
        or not (
            user.is_email_verified
            or user.email_verified_at is not None
            or user.user_id is not None
        )
    ):
        session.revoked_at = now
        db.commit()
        return None
    last_seen = as_utc(session.last_seen_at)
    if last_seen is None or (now - last_seen).total_seconds() > 60:
        session.last_seen_at = now
        db.commit()
    return (
        {
            "id": user.id,
            "username": user.username,
            "user_id": user.user_id,
            "role": user.role,
            "active": user.active,
            "email": user.email,
            "full_name": user.full_name,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "account_type": user.account_type,
            "avatar_url": user.avatar_url,
            "phone": user.phone,
            "department": user.department,
            "usn": user.usn,
            "is_profile_complete": user.is_profile_complete,
        },
        session,
    )


def revoke_session(db: Session, raw_token: str | None) -> bool:
    if not raw_token:
        return False
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(raw_token)))
    if session is None or session.revoked_at is not None:
        return False
    session.revoked_at = now_utc()
    db.commit()
    return True


def csrf_matches(session: AuthSession, header_value: str | None) -> bool:
    if not header_value:
        return False
    return hmac.compare_digest(session.csrf_hash, token_hash(header_value))


def cookie_settings(max_age: int) -> dict:
    settings = {
        "max_age": max_age,
        "path": "/",
        "secure": cookie_secure(),
        "samesite": cookie_samesite(),
    }
    domain = os.getenv("COOKIE_DOMAIN", "").strip()
    if domain:
        settings["domain"] = domain
    return settings


def set_session_cookies(response, raw_session: str, raw_csrf: str) -> None:
    max_age = session_ttl_minutes() * 60
    response.set_cookie(SESSION_COOKIE, raw_session, httponly=True, **cookie_settings(max_age))
    response.set_cookie(CSRF_COOKIE, raw_csrf, httponly=False, **cookie_settings(max_age))


def clear_session_cookies(response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=cookie_secure(), samesite=cookie_samesite())
