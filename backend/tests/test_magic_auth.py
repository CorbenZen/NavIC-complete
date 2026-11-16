"""Passwordless email authentication, session and CSRF regression tests."""

import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request
from starlette.responses import Response

from navic_tcp import auth as auth_service
from navic_tcp import fastapi_app as api
from navic_tcp.db import Base
from navic_tcp.models import AuditLog, AuthSession, MagicLinkToken, User
from navic_tcp.security import LoginRateLimiter, SlidingWindowRateLimiter, hash_password, token_hash


def make_request(ip="127.0.0.1", user_agent="unit-test", method="POST", headers=None, path="/"):
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"user-agent", user_agent.encode()), *(headers or [])],
            "client": (ip, 12345),
        }
    )


class MagicAuthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.patch = patch.object(api, "SessionLocal", self.factory)
        self.patch.start()
        self.ip_limiter = patch.object(api, "_magic_ip_limiter", SlidingWindowRateLimiter(20, 600))
        self.email_limiter = patch.object(api, "_magic_email_limiter", SlidingWindowRateLimiter(3, 600))
        self.login_limiter = patch.object(api, "_login_limiter", LoginRateLimiter())
        self.ip_limiter.start()
        self.email_limiter.start()
        self.login_limiter.start()
        with self.factory() as db:
            db.add(
                User(
                    username="admin@college.edu",
                    email="admin@college.edu",
                    role="admin",
                    password_hash=hash_password("development-password"),
                    is_email_verified=True,
                    email_verified_at=datetime.now(timezone.utc),
                )
            )
            db.commit()

    def tearDown(self):
        self.login_limiter.stop()
        self.email_limiter.stop()
        self.ip_limiter.stop()
        self.patch.stop()
        self.engine.dispose()

    def _request_link(self, email="admin@college.edu"):
        with patch.object(api, "email_delivery_status", return_value={"provider": "console", "configured": True}), patch.object(
            api, "send_magic_link"
        ) as sender:
            result = api.request_magic_link(api.MagicLinkIn(email=email), make_request())
        return result, sender

    def _token_from_link(self):
        _result, sender = self._request_link()
        link = sender.call_args.args[1]
        return parse_qs(urlparse(link).query)["token"][0]

    def test_request_stores_only_a_hash_and_sends_one_labelled_link(self):
        result, sender = self._request_link()
        self.assertIn("authorised account", result["message"])
        sender.assert_called_once()
        recipient, link, ttl = sender.call_args.args
        self.assertEqual(recipient, "admin@college.edu")
        self.assertEqual(ttl, auth_service.magic_link_ttl_minutes())
        self.assertTrue(link.startswith(auth_service.frontend_base_url() + "/auth/verify?token="))
        raw = parse_qs(urlparse(link).query)["token"][0]
        with self.factory() as db:
            row = db.scalar(select(MagicLinkToken))
            self.assertNotEqual(row.token_hash, raw)
            self.assertEqual(row.token_hash, token_hash(raw))
            self.assertIsNone(row.used_at)

    def test_unknown_address_gets_the_same_generic_response_without_email(self):
        result, sender = self._request_link("nobody@college.edu")
        self.assertIn("authorised account", result["message"])
        sender.assert_not_called()
        with self.factory() as db:
            self.assertIsNone(db.scalar(select(MagicLinkToken)))

    def test_verify_consumes_link_once_and_sets_httponly_session_cookies(self):
        raw = self._token_from_link()
        response = Response()
        result = api.verify_magic_link_endpoint(api.VerifyMagicLinkIn(token=raw), make_request(), response)
        self.assertEqual(result["user"]["email"], "admin@college.edu")
        cookie_headers = response.headers.getlist("set-cookie")
        self.assertTrue(any(auth_service.SESSION_COOKIE in header and "HttpOnly" in header for header in cookie_headers))
        self.assertTrue(any(auth_service.CSRF_COOKIE in header for header in cookie_headers))
        with self.factory() as db:
            token = db.scalar(select(MagicLinkToken))
            self.assertIsNotNone(token.used_at)
            user = db.scalar(select(User))
            self.assertIsNotNone(user.email_verified_at)
            self.assertIsNotNone(user.last_login_at)
            self.assertIsNotNone(db.scalar(select(AuthSession)))
        with self.assertRaises(HTTPException) as reused:
            api.verify_magic_link_endpoint(api.VerifyMagicLinkIn(token=raw), make_request(), Response())
        self.assertEqual(reused.exception.status_code, 400)

    def test_expired_link_is_rejected(self):
        raw = self._token_from_link()
        with self.factory() as db:
            token = db.scalar(select(MagicLinkToken))
            token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        with self.assertRaises(HTTPException) as expired:
            api.verify_magic_link_endpoint(api.VerifyMagicLinkIn(token=raw), make_request(), Response())
        self.assertEqual(expired.exception.status_code, 400)

    def test_logout_revokes_the_session(self):
        with self.factory() as db:
            user = db.scalar(select(User))
            raw_session, _csrf, _expires = auth_service.create_session(db, user, make_request())
        response = Response()
        self.assertTrue(api.logout(response, navic_session=raw_session)["signed_out"])
        with self.factory() as db:
            self.assertIsNone(auth_service.resolve_session(db, raw_session))
            session = db.scalar(select(AuthSession))
            self.assertIsNotNone(session.revoked_at)

    def test_unconfigured_email_provider_is_reported_without_creating_a_token(self):
        with patch.object(api, "email_delivery_status", return_value={"provider": "", "configured": False}):
            with self.assertRaises(HTTPException) as unavailable:
                api.request_magic_link(api.MagicLinkIn(email="admin@college.edu"), make_request())
        self.assertEqual(unavailable.exception.status_code, 503)
        with self.factory() as db:
            self.assertIsNone(db.scalar(select(MagicLinkToken)))

    def test_invalid_email_is_rejected_before_rate_limit_or_delivery(self):
        with self.assertRaises(HTTPException) as invalid:
            api.request_magic_link(api.MagicLinkIn(email="not-an-email"), make_request())
        self.assertEqual(invalid.exception.status_code, 422)
        with self.factory() as db:
            self.assertIsNone(db.scalar(select(MagicLinkToken)))

    def test_provider_delivery_failure_is_not_reported_as_sent_and_invalidates_token(self):
        with patch.object(api, "email_delivery_status", return_value={"provider": "smtp", "configured": True}), patch.object(
            api, "send_magic_link", side_effect=api.EmailDeliveryError("provider failure")
        ):
            with self.assertRaises(HTTPException) as failed:
                api.request_magic_link(api.MagicLinkIn(email="admin@college.edu"), make_request())
        self.assertEqual(failed.exception.status_code, 503)
        with self.factory() as db:
            token = db.scalar(select(MagicLinkToken))
            self.assertIsNotNone(token)
            self.assertIsNotNone(token.used_at)
            self.assertEqual(db.scalar(select(func.count()).select_from(User)), 1)

    def test_development_capture_end_to_end_magic_link_session_and_logout(self):
        with patch.object(api, "email_delivery_status", return_value={"provider": "console", "configured": True}), patch.object(
            api, "send_magic_link"
        ) as sender:
            result = api.request_magic_link(api.MagicLinkIn(email="admin@college.edu"), make_request())
        self.assertIn("authorised account", result["message"])
        sender.assert_called_once()
        link = sender.call_args.args[1]
        raw = parse_qs(urlparse(link).query)["token"][0]
        response = Response()
        verified = api.verify_magic_link_endpoint(api.VerifyMagicLinkIn(token=raw), make_request(), response)
        self.assertEqual(verified["user"]["email"], "admin@college.edu")
        cookie_headers = response.headers.getlist("set-cookie")
        self.assertTrue(any(auth_service.SESSION_COOKIE in header and "HttpOnly" in header for header in cookie_headers))
        self.assertTrue(any(auth_service.CSRF_COOKIE in header for header in cookie_headers))
        with self.factory() as db:
            token = db.scalar(select(MagicLinkToken))
            self.assertIsNotNone(token.used_at)
            user = db.scalar(select(User))
            self.assertIsNotNone(user.email_verified_at)
            self.assertIsNotNone(user.last_login_at)
            self.assertIsNotNone(db.scalar(select(AuthSession)))
        logout_response = Response()
        api.logout(logout_response, navic_session=raw)
        with self.factory() as db:
            self.assertIsNone(auth_service.resolve_session(db, raw))

    def test_magic_link_request_rate_limit(self):
        with patch.object(api, "email_delivery_status", return_value={"provider": "console", "configured": True}), patch.object(
            api, "send_magic_link"
        ):
            for _ in range(3):
                api.request_magic_link(api.MagicLinkIn(email="admin@college.edu"), make_request())
            with self.assertRaises(HTTPException) as limited:
                api.request_magic_link(api.MagicLinkIn(email="admin@college.edu"), make_request())
        self.assertEqual(limited.exception.status_code, 429)

    def test_designated_admin_uses_password_and_never_gets_a_magic_link(self):
        with patch.object(api, "email_delivery_status", return_value={"provider": "console", "configured": True}):
            with self.assertRaises(HTTPException) as admin_link:
                api.request_magic_link(api.MagicLinkIn(email="admin@example.invalid"), make_request())
        self.assertEqual(admin_link.exception.status_code, 400)

    def test_existing_admin_magic_link_cannot_bypass_password_authentication(self):
        with self.factory() as db:
            user = db.scalar(select(User).where(User.email == "admin@example.invalid"))
            if user is None:
                db.add(
                    User(
                        username="admin@example.invalid",
                        email="admin@example.invalid",
                        role="admin",
                        active=True,
                        is_email_verified=True,
                        password_hash=hash_password("admin-password"),
                    )
                )
                db.commit()
        with patch.object(api, "email_delivery_status", return_value={"provider": "console", "configured": True}):
            with self.assertRaises(HTTPException) as admin_link:
                api.request_magic_link(api.MagicLinkIn(email="admin@example.invalid"), make_request())
        self.assertEqual(admin_link.exception.status_code, 400)

    def test_admin_password_creates_verified_admin_session_and_refresh_resolves(self):
        with patch.dict(os.environ, {"ADMIN_PASSWORD_HASH": hash_password("admin-pass")}):
            response = Response()
            result = api.admin_login(api.AdminLoginIn(email="admin@example.invalid", password="admin-pass"), make_request(), response)
            self.assertEqual(result["user"]["role"], "admin")
            cookie_headers = response.headers.getlist("set-cookie")
            self.assertTrue(any(auth_service.SESSION_COOKIE in header for header in cookie_headers))
            session_cookie = next(c for c in cookie_headers if auth_service.SESSION_COOKIE in c)
            raw = session_cookie.split(";")[0].split("=", 1)[1]
            with self.factory() as db:
                user = db.scalar(select(User).where(User.email == "admin@example.invalid"))
                self.assertIsNotNone(user)
                self.assertEqual(user.role, "admin")
                session = db.scalar(select(AuthSession).where(AuthSession.token_hash == auth_service.token_hash(raw)))
                self.assertIsNotNone(session)
                self.assertIsNone(session.revoked_at)
                self.assertEqual(session.user_id, user.id)

    def test_admin_rejects_wrong_password_and_legacy_password_route(self):
        with patch.dict(os.environ, {"ADMIN_PASSWORD_HASH": hash_password("correct-password")}):
            response = Response()
            with self.assertRaises(HTTPException) as wrong:
                api.admin_login(api.AdminLoginIn(email="admin@example.invalid", password="wrong-password"), make_request(), response)
            self.assertEqual(wrong.exception.status_code, 401)
            with self.assertRaises(HTTPException) as legacy:
                api.login(api.LoginIn(username="admin@example.invalid", password="correct-password"), make_request(), response)
            self.assertEqual(legacy.exception.status_code, 401)

    def test_admin_login_promotes_existing_account_without_duplicate(self):
        with self.factory() as db:
            db.add(
                User(
                    username="admin@example.invalid",
                    email="admin@example.invalid",
                    role="viewer",
                    active=True,
                    is_email_verified=True,
                )
            )
            db.commit()
        with patch.dict(os.environ, {"ADMIN_PASSWORD_HASH": hash_password("admin-pass")}):
            response = Response()
            result = api.admin_login(api.AdminLoginIn(email="admin@example.invalid", password="admin-pass"), make_request(), response)
            self.assertEqual(result["user"]["role"], "admin")
        with self.factory() as db:
            count = db.scalar(
                select(func.count()).select_from(User).where(User.email == "admin@example.invalid")
            )
            self.assertEqual(count, 1)

    def test_admin_login_rate_limit_locks_out_repeated_failures(self):
        with patch.dict(os.environ, {"ADMIN_PASSWORD_HASH": hash_password("admin-pass")}):
            response = Response()
            for _ in range(6):
                with self.assertRaises(HTTPException) as e:
                    api.admin_login(api.AdminLoginIn(email="admin@example.invalid", password="wrong"), make_request(), response)
            self.assertEqual(e.exception.status_code, 429)

    def test_normal_user_cannot_request_admin_session_or_access_admin_api(self):
        with self.factory() as db:
            db.add(
                User(
                    username="user@college.edu",
                    email="user@college.edu",
                    role="viewer",
                    active=True,
                    is_email_verified=True,
                    password_hash=hash_password("user-pass"),
                )
            )
            db.commit()
        with self.assertRaises(HTTPException) as no_admin:
            api.admin_login(api.AdminLoginIn(email="user@college.edu", password="user-pass"), make_request(), Response())
        self.assertEqual(no_admin.exception.status_code, 401)

    def test_profile_completion_persists_fields_without_changing_role(self):
        with self.factory() as db:
            user = User(
                username="profile@college.edu",
                email="profile@college.edu",
                role="viewer",
                active=True,
                is_email_verified=True,
                is_profile_complete=False,
                password_hash=hash_password("pass"),
            )
            db.add(user)
            db.commit()
            user_id = user.id

        result = api.update_user_profile(
            api.UserProfileIn(full_name="Profile Person", phone="+91-9000000000", department="CSE", usn="1HK24CS001"),
            user={"id": user_id, "role": "viewer"},
        )
        self.assertEqual(result["full_name"], "Profile Person")
        self.assertEqual(result["department"], "CSE")
        self.assertTrue(result["is_profile_complete"])
        self.assertEqual(result["role"], "viewer")
        with self.factory() as db:
            self.assertEqual(db.get(User, user_id).role, "viewer")

    def test_profile_endpoint_rejects_frontend_role_assignment(self):
        with self.assertRaises(ValidationError):
            api.UserProfileIn(
                full_name="Profile Person",
                phone="+91-9000000000",
                department="CSE",
                role="admin",
            )

    def test_session_resolves_without_a_bearer_token(self):
        with self.factory() as db:
            user = db.scalar(select(User).where(User.email == "admin@college.edu"))
            raw_session, _csrf, _expires = auth_service.create_session(db, user, make_request())
            resolved = auth_service.resolve_session(db, raw_session)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved[0]["email"], "admin@college.edu")
        self.assertEqual(api.current_user(authorization=None, navic_session=raw_session)["email"], "admin@college.edu")

    def test_expired_session_is_rejected_and_revoked(self):
        with self.factory() as db:
            user = db.scalar(select(User).where(User.email == "admin@college.edu"))
            raw_session, _csrf, _expires = auth_service.create_session(db, user, make_request())
            session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(raw_session)))
            session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        with self.factory() as db:
            self.assertIsNone(auth_service.resolve_session(db, raw_session))
            self.assertIsNotNone(
                db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(raw_session))).revoked_at
            )

    def test_mismatched_csrf_header_is_rejected(self):
        with self.factory() as db:
            user = db.scalar(select(User).where(User.email == "admin@college.edu"))
            raw_session, csrf, _expires = auth_service.create_session(db, user, make_request())
        cookie = f"{auth_service.SESSION_COOKIE}={raw_session}; {auth_service.CSRF_COOKIE}={csrf}".encode()
        request = make_request(headers=[(b"cookie", cookie), (b"x-csrf-token", b"wrong-token")])

        async def call_next(_request):
            return Response()

        response = asyncio.run(api.csrf_protection(request, call_next))
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"CSRF", response.body)

    def test_expired_session_cookie_does_not_block_public_login(self):
        csrf = "matching-but-stale-session-csrf"
        cookie = f"{auth_service.SESSION_COOKIE}=expired-session; {auth_service.CSRF_COOKIE}={csrf}".encode()
        request = make_request(
            headers=[(b"cookie", cookie), (b"x-csrf-token", csrf.encode())],
            path="/api/auth/login",
        )
        reached_login = False

        async def call_next(_request):
            nonlocal reached_login
            reached_login = True
            return Response(status_code=200)

        response = asyncio.run(api.csrf_protection(request, call_next))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(reached_login)

    def test_expired_session_cookie_still_blocks_protected_writes(self):
        csrf = "matching-but-stale-session-csrf"
        cookie = f"{auth_service.SESSION_COOKIE}=expired-session; {auth_service.CSRF_COOKIE}={csrf}".encode()
        request = make_request(headers=[(b"cookie", cookie), (b"x-csrf-token", csrf.encode())])

        async def call_next(_request):
            self.fail("A protected request with an invalid session must not reach its handler")

        response = asyncio.run(api.csrf_protection(request, call_next))
        self.assertEqual(response.status_code, 401)
        self.assertIn(b"session is invalid or expired", response.body)

    def test_legacy_password_login_still_works_for_api_clients(self):
        with self.factory() as db:
            db.add(
                User(
                    username="legacy@college.edu",
                    email="legacy@college.edu",
                    role="viewer",
                    active=True,
                    is_email_verified=True,
                    password_hash=hash_password("legacy-pass"),
                )
            )
            db.commit()
        response = Response()
        result = api.login(api.LoginIn(username="legacy@college.edu", password="legacy-pass"), make_request(), response)
        self.assertIn("access_token", result)
        self.assertEqual(result["user"]["email"], "legacy@college.edu")

    def test_cookie_writes_require_matching_csrf_header(self):
        with self.factory() as db:
            user = db.scalar(select(User).where(User.email == "admin@college.edu"))
            raw_session, _csrf, _expires = auth_service.create_session(db, user, make_request())
        response = Response()
        api.logout(response, navic_session=raw_session)
        self.assertTrue(response.headers.getlist("set-cookie"))

    def test_cross_origin_csrf_bootstrap_requires_a_valid_session_cookie(self):
        with self.factory() as db:
            user = db.scalar(select(User).where(User.email == "admin@college.edu"))
            raw_session, csrf, _expires = auth_service.create_session(db, user, make_request())
        cookie = f"{auth_service.SESSION_COOKIE}={raw_session}; {auth_service.CSRF_COOKIE}={csrf}".encode()
        request = make_request(
            headers=[
                (b"cookie", cookie),
                (b"x-csrf-token", csrf.encode()),
                (b"origin", b"https://evil.example.com"),
            ]
        )

        async def call_next(_request):
            return Response()

        response = asyncio.run(api.csrf_protection(request, call_next))
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"cross-origin", response.body)

    def test_magic_link_and_login_events_are_audited(self):
        with patch.object(api, "email_delivery_status", return_value={"provider": "console", "configured": True}), patch.object(
            api, "send_magic_link"
        ):
            api.request_magic_link(api.MagicLinkIn(email="admin@college.edu"), make_request())
        with self.factory() as db:
            audit = db.scalar(select(AuditLog).where(AuditLog.action == "magic_link_sent"))
            self.assertIsNotNone(audit)
            self.assertEqual(audit.entity, "user")


if __name__ == "__main__":
    unittest.main()
