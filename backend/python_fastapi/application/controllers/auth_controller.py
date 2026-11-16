"""Authentication controller with verified-password and email-link flows."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import Cookie, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.python_fastapi.application.controllers.base import Controller
from backend.python_fastapi.application.core.dependencies import current_user
from backend.python_pydantic.schemas.email_verification import (
    PasswordLoginIn,
    RegisterIn,
    ResendVerificationIn,
    VerifyEmailIn,
)
from backend.python_pydantic.schemas.id_auth import IdLoginIn, RegisterAccountIn
from backend.python_services import auth_service as auth_domain
from backend.python_services.email_service import (
    EmailConfigurationError,
    EmailDeliveryError,
    email_status,
    send_email_verification,
)
from backend.python_sqlalchemy.database.session import SessionLocal
from navic_tcp import auth as session_auth
from navic_tcp import fastapi_app as shared
from navic_tcp.models import User
from navic_tcp.security import (
    LoginRateLimiter,
    SlidingWindowRateLimiter,
    hash_password,
    password_needs_rehash,
    verify_password,
)

_password_login_limiter = LoginRateLimiter()
_id_login_limiter = LoginRateLimiter()
_verification_ip_limiter = SlidingWindowRateLimiter(max_requests=8, window_seconds=900)
_verification_email_limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=900)
_registration_limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=900)
_id_registration_limiter = SlidingWindowRateLimiter(max_requests=10, window_seconds=900)
_VERIFICATION_RESEND_COOLDOWN_SECONDS = 60
_DUPLICATE_EMAIL = "An account with this email already exists. Please sign in instead."
_DUPLICATE_ID = "This ID is already registered. Please choose another ID."
_DUPLICATE_USN = "This student USN is already registered."
_UNKNOWN_ID = "Incorrect User ID or password"
_BAD_PASSWORD = "Incorrect User ID or password"


def _public_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
        "account_type": user.account_type,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "second_name": user.second_name or user.last_name,
        "full_name": user.full_name,
        "usn": user.usn,
        "usn_id": user.usn,
        "is_profile_complete": user.is_profile_complete,
    }


def _establish_session(db, user: User, request: Request, response: Response, method: str = "email_password") -> dict:
    now = datetime.now(timezone.utc)
    user.last_login_at = now
    shared._audit(db, {"username": user.username, "role": user.role}, "login", "user", user.id, f"method={method}")
    db.commit()
    raw_session, csrf_token, expires = session_auth.create_session(db, user, request)
    session_auth.set_session_cookies(response, raw_session, csrf_token)
    return {
        "access_token": shared.issue_token(user.username),
        "token_type": "bearer",
        "expires_in": int((expires - now).total_seconds()),
        "csrf_token": csrf_token,
        "user": _public_user(user),
    }


def _send_verification(db, user: User) -> int:
    """Send a token or reuse the existing pending token during the cooldown."""
    now = datetime.now(timezone.utc)
    sent_at = session_auth.as_utc(user.email_verification_sent_at)
    expires = session_auth.as_utc(user.email_verification_expires_at)
    if (
        user.email_verification_token_hash
        and expires and expires > now
        and sent_at
        and (now - sent_at).total_seconds() < _VERIFICATION_RESEND_COOLDOWN_SECONDS
    ):
        return max(1, _VERIFICATION_RESEND_COOLDOWN_SECONDS - int((now - sent_at).total_seconds()))

    if not email_status()["configured"]:
        raise HTTPException(503, "Email verification is unavailable because email delivery is not configured.")
    if not session_auth.is_development() and urlsplit(auth_domain.frontend_base_url()).scheme != "https":
        raise HTTPException(503, "Secure email verification requires an HTTPS FRONTEND_URL in production.")
    raw_token, _expires = auth_domain.create_email_verification(db, user)
    db.commit()
    try:
        send_email_verification(
            user.email,
            auth_domain.email_verification_link(raw_token),
            auth_domain.email_verification_expire_minutes(),
            first_name=user.first_name,
        )
    except (EmailConfigurationError, EmailDeliveryError, ValueError):
        user.email_verification_token_hash = None
        user.email_verification_expires_at = None
        user.email_verification_sent_at = None
        db.commit()
        raise HTTPException(503, "The verification email could not be delivered. Please try again later.") from None
    return 0


def password_login(data: PasswordLoginIn, request: Request, response: Response):
    """Check credentials before sending verification; issue no session until verified."""
    client = session_auth.client_ip(request)
    key = f"{client}:{data.email}"
    wait = _password_login_limiter.retry_after(key)
    if wait:
        raise HTTPException(429, "Too many sign-in attempts. Try again later.", headers={"Retry-After": str(wait)})
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(func.trim(User.email)) == data.email, User.active.is_(True)))
        if user is None:
            _password_login_limiter.fail(key)
            raise HTTPException(404, "No account found with this email. Please create an account.")
        if user.role != "admin" and not user.password_hash:
            _password_login_limiter.reset(key)
            raise HTTPException(
                409,
                "This account does not have a password. Use the one-time email sign-in link or Google sign-in instead.",
            )
        if user.role == "admin" or not verify_password(data.password, user.password_hash):
            _password_login_limiter.fail(key)
            raise HTTPException(401, "Invalid email or password.")
        _password_login_limiter.reset(key)
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(data.password)
        if not auth_domain.is_email_verified(user):
            _send_verification(db, user)
            response.status_code = 202
            return {
                "verification_required": True,
                "message": "Check your inbox for a link to verify your email before signing in.",
                "expires_in": auth_domain.email_verification_expire_minutes() * 60,
            }
        user.is_email_verified = True
        user.email_verified_at = user.email_verified_at or datetime.now(timezone.utc)
        return _establish_session(db, user, request, response)


def register(data: RegisterIn, request: Request, response: Response):
    """Create an unverified student/teacher account and send its verification link."""
    ip = session_auth.client_ip(request)
    allowed, retry = _registration_limiter.allow(f"ip:{ip}")
    if not allowed:
        raise HTTPException(429, "Too many account-creation attempts. Try again later.", headers={"Retry-After": str(retry)})
    with SessionLocal() as db:
        existing = db.scalar(select(User.id).where(func.lower(func.trim(User.email)) == data.email))
        if existing is not None:
            raise HTTPException(409, _DUPLICATE_EMAIL)
        if not email_status()["configured"]:
            raise HTTPException(503, "Email verification is unavailable because email delivery is not configured.")
        username = data.email if len(data.email) <= 120 else "gmail_" + hashlib.sha256(data.email.encode()).hexdigest()[:48]
        user = User(
            username=username,
            email=data.email,
            first_name=data.first_name,
            last_name=data.last_name,
            second_name=data.last_name,
            full_name=f"{data.first_name} {data.last_name}",
            account_type=data.account_type,
            usn=data.usn_id if data.account_type == "student" else None,
            role="viewer",
            active=True,
            is_profile_complete=True,
            is_email_verified=False,
            password_hash=hash_password(data.password),
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # The unique normalized email/USN indexes close the race between
            # preflight validation and concurrent registration requests.
            email_exists = db.scalar(select(User.id).where(func.lower(func.trim(User.email)) == data.email))
            if email_exists is not None:
                raise HTTPException(409, _DUPLICATE_EMAIL) from None
            raise HTTPException(409, "This student USN is already registered.") from None
        db.refresh(user)
        try:
            _send_verification(db, user)
        except HTTPException as exc:
            if exc.status_code == 503:
                raise HTTPException(
                    503,
                    "Account created, but the verification email could not be delivered. Sign in to retry when email delivery is available.",
                ) from None
            raise
        response.status_code = 201
        return {
            "verification_required": True,
            "message": "Account created. Check your inbox for a verification link before signing in.",
            "email": user.email,
            "expires_in": auth_domain.email_verification_expire_minutes() * 60,
        }


def register_account(data: RegisterAccountIn, request: Request, response: Response):
    """Create a student or teacher account identified only by ``user_id``.

    No email address, SMTP configuration or verification mail participates in
    this flow.  Passwords are hashed with the shared scrypt implementation and
    never logged or returned.
    """
    ip = session_auth.client_ip(request)
    allowed, retry = _id_registration_limiter.allow(f"register:{ip}")
    if not allowed:
        raise HTTPException(429, "Too many account-creation attempts. Try again later.", headers={"Retry-After": str(retry)})

    with SessionLocal() as db:
        existing_id = db.scalar(
            select(User.id).where(func.lower(func.trim(User.user_id)) == data.user_id.lower())
        )
        if existing_id is not None:
            raise HTTPException(409, _DUPLICATE_ID)
        if data.account_type == "student":
            existing_usn = db.scalar(
                select(User.id).where(
                    func.lower(func.trim(User.usn)) == data.usn_id.lower(),
                    User.account_type == "student",
                )
            )
            if existing_usn is not None:
                raise HTTPException(409, _DUPLICATE_USN)

        user = User(
            username=data.user_id,
            user_id=data.user_id,
            email=None,
            first_name=data.first_name,
            last_name=data.last_name,
            second_name=data.last_name,
            full_name=f"{data.first_name} {data.last_name}",
            account_type=data.account_type,
            usn=data.usn_id if data.account_type == "student" else None,
            role="viewer",
            active=True,
            is_profile_complete=True,
            # This account has no email identity; it is authorised by its
            # password and must not be blocked by the email-verification gate.
            is_email_verified=True,
            password_hash=hash_password(data.password),
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # The unique indexes close the race between the preflight check and
            # a concurrent registration for the same ID or student USN.
            duplicate_id = db.scalar(
                select(User.id).where(func.lower(func.trim(User.user_id)) == data.user_id.lower())
            )
            if duplicate_id is not None:
                raise HTTPException(409, _DUPLICATE_ID) from None
            raise HTTPException(409, _DUPLICATE_USN) from None
        db.refresh(user)
        response.status_code = 201
        return {
            "message": "Account created. You can now sign in with your User ID and password.",
            "user": _public_user(user),
        }


def _admin_id_login(identifier: str, password: str, request: Request, response: Response, key: str):
    """Authenticate the configured administrator without changing its authority.

    The administrator credential remains the value configured through
    ``ADMIN_EMAIL``/``ADMIN_PASSWORD_HASH``; signing in through the normal form
    simply reuses that check and then issues the same database-backed session.
    """
    if not verify_password(password, os.getenv("ADMIN_PASSWORD_HASH", "").strip()):
        _id_login_limiter.fail(key)
        raise HTTPException(401, _BAD_PASSWORD)
    email = shared.configured_admin_email()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user is not None and not user.active:
            _id_login_limiter.fail(key)
            raise HTTPException(401, _BAD_PASSWORD)
        if user is None:
            # ``user_id`` is globally unique; never collide with a normal
            # account that happens to have chosen the identifier "ADMIN".
            candidate = "ADMIN"
            taken = db.scalar(
                select(User.id).where(func.lower(func.trim(User.user_id)) == candidate.lower())
            )
            if taken is not None:
                candidate = f"ADMIN-{secrets.token_hex(4).upper()}"
            user = User(username=email, email=email, user_id=candidate, role="admin", active=True)
            db.add(user)
            db.flush()
        elif not user.user_id:
            candidate = "ADMIN"
            taken = db.scalar(
                select(User.id).where(func.lower(func.trim(User.user_id)) == candidate.lower())
            )
            user.user_id = candidate if taken is None else f"ADMIN-{secrets.token_hex(4).upper()}"
        user.role = "admin"
        user.active = True
        user.email_verified_at = user.email_verified_at or datetime.now(timezone.utc)
        user.is_email_verified = True
        _id_login_limiter.reset(key)
        payload = _establish_session(db, user, request, response, method="admin_password")
    return payload


def id_login(data: IdLoginIn, request: Request, response: Response):
    """Verify a User ID and password and create a browser session."""
    client = session_auth.client_ip(request)
    identifier = data.user_id
    key = f"id:{client}:{identifier}"
    wait = _id_login_limiter.retry_after(key)
    if wait:
        raise HTTPException(429, "Too many sign-in attempts. Try again later.", headers={"Retry-After": str(wait)})

    if identifier.lower() == shared.configured_admin_email():
        return _admin_id_login(identifier, data.password, request, response, key)

    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(
                func.lower(func.trim(User.user_id)) == identifier.lower(),
                User.active.is_(True),
            )
        )
        if user is None:
            _id_login_limiter.fail(key)
            raise HTTPException(401, _UNKNOWN_ID)
        if user.role == "admin":
            # Administrator credentials are only accepted through the
            # configured admin email + password check above.
            _id_login_limiter.fail(key)
            raise HTTPException(401, _BAD_PASSWORD)
        if not user.password_hash or not verify_password(data.password, user.password_hash):
            _id_login_limiter.fail(key)
            raise HTTPException(401, _BAD_PASSWORD)
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(data.password)
        _id_login_limiter.reset(key)
        return _establish_session(db, user, request, response, method="id_password")


def verify_email(data: VerifyEmailIn, request: Request, response: Response):
    with SessionLocal() as db:
        user = auth_domain.verify_email_token(db, data.token)
        if user is None or not user.active or user.role == "admin":
            raise HTTPException(400, "This verification link is invalid, expired, or has already been used.")
        payload = _establish_session(db, user, request, response)
        payload["email_verified"] = True
        return payload


def resend_verification(data: ResendVerificationIn, request: Request, response: Response):
    ip = session_auth.client_ip(request)
    allowed_ip, retry_ip = _verification_ip_limiter.allow(f"ip:{ip}")
    allowed_email, retry_email = _verification_email_limiter.allow(f"email:{data.email}")
    if not allowed_ip or not allowed_email:
        retry = max(retry_ip, retry_email, 1)
        raise HTTPException(429, "Too many verification requests. Wait before trying again.", headers={"Retry-After": str(retry)})
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == data.email, User.active.is_(True)))
        if user is not None and user.role != "admin" and not auth_domain.is_email_verified(user):
            _send_verification(db, user)
    response.status_code = 202
    return {"message": "If the account needs verification, an email has been sent."}


def verification_status(user=Depends(current_user)):
    # An active session cannot be established by this application before the
    # email address is verified (Google/admin have their own verified proofs).
    return {"is_email_verified": True}


def me(user=Depends(current_user)):
    """Return the authenticated principal's public fields."""
    return user


def logout(response: Response, navic_session: str | None = Cookie(default=None)):
    """Revoke the browser session and clear both auth cookies."""
    with SessionLocal() as db:
        if navic_session:
            session_auth.revoke_session(db, navic_session)
    session_auth.clear_session_cookies(response)
    return {"signed_out": True}


class AuthController(Controller):
    operations = {
        "/auth/login": password_login,
        "/auth/register": register_account,
        "/auth/me": me,
        "/auth/logout": logout,
    }


__all__ = [
    "AuthController",
    "id_login",
    "logout",
    "me",
    "password_login",
    "register",
    "register_account",
    "resend_verification",
    "verification_status",
    "verify_email",
]
