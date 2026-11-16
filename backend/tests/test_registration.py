"""User ID + password registration and login tests.

Covers the student/teacher contracts, uniqueness, password safety, session
creation, protected access, logout, the configured administrator and the
retained Google entry point.  No email address or SMTP service is used.
"""

from __future__ import annotations

import os
import re
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request
from starlette.responses import Response

from backend.python_fastapi.application.controllers import auth_controller as controller
from backend.python_pydantic.schemas.id_auth import (
    IdLoginIn,
    RegisterAccountIn,
    normalize_user_id,
)
from backend.python_services import auth_service as auth_domain
from navic_tcp import fastapi_app as shared
from navic_tcp.models import AuditLog, Base, User
from navic_tcp.security import hash_password


def request_for(ip=None):
    ip = ip or f"192.0.2.{int(uuid4().hex[:2], 16)}"
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/login",
            "headers": [(b"user-agent", b"id-password-tests")],
            "client": (ip, 12345),
        }
    )


def reset_limiters():
    for limiter in (
        controller._id_login_limiter,
        controller._id_registration_limiter,
        controller._registration_limiter,
    ):
        with limiter._lock:
            if hasattr(limiter, "_buckets"):
                limiter._buckets.clear()
            if hasattr(limiter, "_events"):
                limiter._events.clear()


def session_cookie(response: Response) -> str:
    for header in response.headers.getlist("set-cookie"):
        match = re.search(r"navic_session=([^;]+)", header)
        if match:
            return match.group(1)
    raise AssertionError("session cookie was not set")


class IdPasswordAuthTests(unittest.TestCase):
    def setUp(self):
        reset_limiters()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.db_patch = patch.object(controller, "SessionLocal", self.factory)
        self.db_patch.start()
        self.shared_patch = patch.object(shared, "SessionLocal", self.factory)
        self.shared_patch.start()

    def tearDown(self):
        self.shared_patch.stop()
        self.db_patch.stop()
        self.engine.dispose()

    def data(self, **overrides):
        values = {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "account_type": "student",
            "user_id": f"NAVIC{uuid4().hex[:8].upper()}",
            "usn_id": f"1AB23CS{uuid4().hex[:3].upper()}",
            "password": "secure-password",
            "confirm_password": "secure-password",
        }
        values.update(overrides)
        return RegisterAccountIn(**values)

    def register(self, data=None):
        response = Response()
        result = controller.register_account(data or self.data(), request_for(), response)
        return result, response

    def login(self, user_id, password="secure-password"):
        response = Response()
        result = controller.id_login(IdLoginIn(user_id=user_id, password=password), request_for(), response)
        return result, response

    def user(self, user_id):
        with self.factory() as db:
            return db.scalar(select(User).where(func_lower_user_id(user_id)))

    # 1 ------------------------------------------------------------------
    def test_student_registration_persists_hashed_password_without_email(self):
        data = self.data(first_name=" Ada ", last_name=" Lovelace ", user_id=f" navic{uuid4().hex[:6]} ")
        result, response = self.register(data)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(result["user"]["user_id"], data.user_id.upper())
        self.assertEqual(result["user"]["account_type"], "student")
        self.assertEqual(result["user"]["usn_id"], data.usn_id.upper())
        self.assertIsNone(result["user"]["email"])
        user = self.user(data.user_id)
        self.assertIsNotNone(user)
        self.assertIsNone(user.email)
        self.assertNotEqual(user.password_hash, data.password)
        self.assertTrue(user.password_hash.startswith("scrypt$"))
        self.assertNotIn(data.password, user.password_hash)
        self.assertEqual((user.first_name, user.last_name), ("Ada", "Lovelace"))
        self.assertEqual(user.second_name, "Lovelace")
        self.assertEqual(user.role, "viewer")

    # 2, 4 ---------------------------------------------------------------
    def test_teacher_registration_succeeds_without_usn(self):
        data = self.data(account_type="teacher", usn_id=None)
        result, response = self.register(data)
        self.assertEqual(response.status_code, 201)
        user = self.user(data.user_id)
        self.assertEqual(user.account_type, "teacher")
        self.assertIsNone(user.usn)
        self.assertIsNone(result["user"]["usn_id"])

    def test_teacher_registration_rejects_a_usn(self):
        with self.assertRaises(ValidationError):
            self.data(account_type="teacher", usn_id="1AB23CS777")

    # 3 ------------------------------------------------------------------
    def test_student_registration_without_usn_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.data(account_type="student", usn_id=None)
        with self.assertRaises(ValidationError):
            self.data(account_type="student", usn_id="   ")

    # 5 ------------------------------------------------------------------
    def test_duplicate_user_id_is_rejected_case_insensitively(self):
        first = self.data()
        self.register(first)
        with self.assertRaises(HTTPException) as duplicate:
            self.register(self.data(user_id=first.user_id.lower()))
        self.assertEqual(duplicate.exception.status_code, 409)
        self.assertEqual(duplicate.exception.detail, "This ID is already registered. Please choose another ID.")
        with self.factory() as db:
            self.assertEqual(db.query(User).filter(User.user_id == first.user_id).count(), 1)

    # 6 ------------------------------------------------------------------
    def test_duplicate_student_usn_is_rejected(self):
        first = self.data()
        self.register(first)
        with self.assertRaises(HTTPException) as duplicate:
            self.register(self.data(usn_id=first.usn_id.lower()))
        self.assertEqual(duplicate.exception.status_code, 409)
        self.assertEqual(duplicate.exception.detail, "This student USN is already registered.")

    # 7 ------------------------------------------------------------------
    def test_login_with_correct_id_and_password_creates_session(self):
        data = self.data()
        self.register(data)
        result, response = self.login(data.user_id.lower())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["user"]["user_id"], data.user_id)
        self.assertTrue(result["access_token"])
        self.assertTrue(result["csrf_token"])
        raw = session_cookie(response)
        with self.factory() as db:
            resolved = auth_domain.resolve_session(db, raw)
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved[0]["user_id"], data.user_id)
            user = db.scalar(select(User).where(func_lower_user_id(data.user_id)))
            self.assertIsNotNone(user.last_login_at)
            self.assertEqual(db.query(AuditLog).filter_by(action="login", entity="user").count(), 1)

    # 8 ------------------------------------------------------------------
    def test_incorrect_password_is_rejected(self):
        data = self.data()
        self.register(data)
        with self.assertRaises(HTTPException) as bad:
            self.login(data.user_id, password="wrong-password")
        self.assertEqual(bad.exception.status_code, 401)
        self.assertEqual(bad.exception.detail, "Incorrect User ID or password")

    # 9 ------------------------------------------------------------------
    def test_unknown_id_is_rejected(self):
        with self.assertRaises(HTTPException) as missing:
            self.login("NOSUCHID")
        self.assertEqual(missing.exception.status_code, 401)
        self.assertEqual(missing.exception.detail, "Incorrect User ID or password")

    def test_client_cannot_set_privileged_role(self):
        values = self.data().model_dump()
        values["role"] = "admin"
        with self.assertRaises(ValidationError):
            RegisterAccountIn(**values)

    def test_session_cookie_authenticates_then_logout_revokes_protected_access(self):
        data = self.data()
        self.register(data)
        _payload, response = self.login(data.user_id)
        raw = session_cookie(response)
        with patch.object(shared, "DEMO_AUTH_BYPASS", False):
            authenticated = shared.current_user(authorization=None, navic_session=raw)
            self.assertEqual(authenticated["user_id"], data.user_id)
            controller.logout(Response(), navic_session=raw)
            with self.assertRaises(HTTPException) as revoked:
                shared.current_user(authorization=None, navic_session=raw)
            self.assertEqual(revoked.exception.status_code, 401)

    def test_demo_bypass_uses_real_account_when_session_cookie_is_present(self):
        data = self.data()
        self.register(data)
        _payload, response = self.login(data.user_id)
        with patch.object(shared, "DEMO_AUTH_BYPASS", True):
            self.assertEqual(shared.current_user(authorization=None, navic_session=None)["username"], "demo")
            actual = shared.current_user(authorization=None, navic_session=session_cookie(response))
            self.assertEqual(actual["user_id"], data.user_id)

    def test_openapi_register_and_login_methods_are_post(self):
        from backend.python_fastapi.application.main import app

        paths = app.openapi()["paths"]
        self.assertIn("post", paths["/api/auth/register"])
        self.assertIn("post", paths["/api/auth/login"])

    # empty fields
    def test_empty_credentials_are_rejected_by_validation(self):
        with self.assertRaises(ValidationError):
            IdLoginIn(user_id="", password="")
        with self.assertRaises(ValidationError):
            IdLoginIn(user_id="   ", password="something")

    # 10 -----------------------------------------------------------------
    def test_protected_dependency_rejects_unauthenticated_requests(self):
        with self.assertRaises(HTTPException) as unauthorised:
            shared.current_user(authorization=None, navic_session=None)
        self.assertEqual(unauthorised.exception.status_code, 401)

    # 11 -----------------------------------------------------------------
    def test_logout_revokes_the_session(self):
        data = self.data()
        self.register(data)
        _result, response = self.login(data.user_id)
        raw = session_cookie(response)
        with self.factory() as db:
            self.assertIsNotNone(auth_domain.resolve_session(db, raw))
        controller.logout(Response(), navic_session=raw)
        with self.factory() as db:
            self.assertIsNone(auth_domain.resolve_session(db, raw))

    # 12 -----------------------------------------------------------------
    def test_configured_admin_can_still_sign_in(self):
        admin_email = f"admin-{uuid4().hex[:6]}@college.example"
        password = "admin-password-123"
        with patch.dict(
            os.environ,
            {"ADMIN_EMAIL": admin_email, "ADMIN_PASSWORD_HASH": hash_password(password)},
        ):
            result, response = self.login(admin_email, password=password)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["user"]["role"], "admin")
        self.assertTrue(session_cookie(response))

    def test_admin_login_does_not_collide_with_a_normal_admin_named_user(self):
        # A normal account may legitimately register the identifier "ADMIN".
        self.register(self.data(user_id="ADMIN"))
        admin_email = f"admin-{uuid4().hex[:6]}@college.example"
        password = "admin-password-123"
        with patch.dict(
            os.environ,
            {"ADMIN_EMAIL": admin_email, "ADMIN_PASSWORD_HASH": hash_password(password)},
        ):
            result, response = self.login(admin_email, password=password)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["user"]["role"], "admin")
        self.assertNotEqual(result["user"]["user_id"], "ADMIN")

    # extra ---------------------------------------------------------------
    def test_user_id_format_and_normalisation(self):
        self.assertEqual(normalize_user_id("  navic.001 "), "NAVIC.001")
        # The administrator signs in by entering the configured email in the
        # same field; it is normalised for a case-insensitive comparison.
        self.assertEqual(
            IdLoginIn(user_id=" Admin@College.Example ", password="something").user_id,
            "admin@college.example",
        )
        for invalid in ("ab", "has space", "-LEADING", "x" * 33, "", "not-an-email@", "two@@at.com"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    IdLoginIn(user_id=invalid, password="something")

    def test_password_must_match_and_respect_minimum_length(self):
        with self.assertRaises(ValidationError):
            self.data(confirm_password="different-password")
        with self.assertRaises(ValidationError):
            self.data(password="short1", confirm_password="short1")
        with self.assertRaises(ValidationError):
            self.data(password="12345678", confirm_password="12345678")

    def test_database_unique_index_rejects_racing_user_id(self):
        first = self.data()
        self.register(first)
        with self.factory() as db:
            db.add(
                User(
                    username=f"other-{uuid4().hex}",
                    user_id=first.user_id.lower(),
                    role="viewer",
                    active=True,
                    password_hash=hash_password("another-password"),
                    is_email_verified=True,
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_password_is_never_returned_or_logged(self):
        data = self.data()
        result, _response = self.register(data)
        serialised = str(result)
        self.assertNotIn(data.password, serialised)
        self.assertNotIn("password_hash", serialised.lower())
        self.assertNotIn(data.password, str(result["user"]))


def func_lower_user_id(value):
    from sqlalchemy import func

    return func.lower(func.trim(User.user_id)) == value.lower()


if __name__ == "__main__":
    unittest.main()
