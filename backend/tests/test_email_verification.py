"""Email-verification and password-login security regression tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request
from starlette.responses import Response

from backend.python_fastapi.application.controllers import auth_controller as controller
from backend.python_pydantic.schemas.email_verification import (
    PasswordLoginIn,
    ResendVerificationIn,
    VerifyEmailIn,
)
from navic_tcp import emailer
from navic_tcp.emailer import EmailDeliveryError
from navic_tcp.models import AuthSession, Base, User
from navic_tcp.security import hash_password, token_hash


def make_request(ip: str = "127.0.0.42") -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/auth/login",
        "headers": [(b"user-agent", b"email-verification-test")],
        "client": (ip, 12345),
    })


class EmailVerificationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.session_factory_patch = patch.object(controller, "SessionLocal", self.factory)
        self.session_factory_patch.start()
        self.delivery_config_patch = patch.object(controller, "email_status", return_value={"configured": True})
        self.delivery_config_patch.start()
        self.development_patch = patch.object(controller.session_auth, "is_development", return_value=True)
        self.development_patch.start()
        self.email_patch = patch.object(controller, "send_email_verification")
        self.sender = self.email_patch.start()
        self.email = f"verify-{uuid4().hex}@college.example"
        with self.factory() as db:
            db.add(User(
                username=self.email,
                email=self.email,
                role="viewer",
                active=True,
                password_hash=hash_password("correct horse battery"),
                is_email_verified=False,
            ))
            db.commit()

    def tearDown(self):
        self.email_patch.stop()
        self.delivery_config_patch.stop()
        self.development_patch.stop()
        self.session_factory_patch.stop()
        self.engine.dispose()

    def _password_login(self, *, email=None, password="correct horse battery"):
        response = Response()
        payload = controller.password_login(
            PasswordLoginIn(email=email or self.email, password=password),
            make_request(),
            response,
        )
        return payload, response

    def _token_from_email(self, call_index=-1):
        link = self.sender.call_args_list[call_index].args[1]
        return parse_qs(urlparse(link).query)["token"][0]

    def test_unverified_valid_password_sends_mail_without_authentication(self):
        payload, response = self._password_login()
        self.assertEqual(response.status_code, 202)
        self.assertTrue(payload["verification_required"])
        self.assertNotIn("access_token", payload)
        self.assertFalse(response.headers.getlist("set-cookie"))
        self.sender.assert_called_once()
        raw = self._token_from_email()
        with self.factory() as db:
            user = db.scalar(select(User).where(User.email == self.email))
            self.assertEqual(user.email_verification_token_hash, token_hash(raw))
            self.assertNotEqual(user.email_verification_token_hash, raw)
            self.assertIsNone(db.scalar(select(AuthSession).where(AuthSession.user_id == user.id)))

    def test_verification_creates_session_and_token_is_one_time(self):
        self._password_login()
        raw = self._token_from_email()
        response = Response()
        result = controller.verify_email(VerifyEmailIn(token=raw), make_request(), response)
        self.assertTrue(result["email_verified"])
        self.assertTrue(result["access_token"])
        self.assertTrue(response.headers.getlist("set-cookie"))
        with self.factory() as db:
            user = db.scalar(select(User).where(User.email == self.email))
            self.assertTrue(user.is_email_verified)
            self.assertIsNotNone(user.email_verified_at)
            self.assertIsNone(user.email_verification_token_hash)
        with self.assertRaises(HTTPException) as reused:
            controller.verify_email(VerifyEmailIn(token=raw), make_request(), Response())
        self.assertEqual(reused.exception.status_code, 400)

    def test_invalid_and_expired_tokens_do_not_create_sessions(self):
        self._password_login()
        with self.assertRaises(HTTPException) as invalid:
            controller.verify_email(VerifyEmailIn(token="x" * 32), make_request(), Response())
        self.assertEqual(invalid.exception.status_code, 400)
        raw = self._token_from_email()
        with self.factory() as db:
            user = db.scalar(select(User).where(User.email == self.email))
            user.email_verification_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        with self.assertRaises(HTTPException) as expired:
            controller.verify_email(VerifyEmailIn(token=raw), make_request(), Response())
        self.assertEqual(expired.exception.status_code, 400)
        with self.factory() as db:
            self.assertIsNone(db.scalar(select(AuthSession)))

    def test_verified_password_login_creates_session(self):
        with self.factory() as db:
            user = db.scalar(select(User).where(User.email == self.email))
            user.is_email_verified = True
            user.email_verified_at = datetime.now(timezone.utc)
            db.commit()
        payload, response = self._password_login()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["access_token"])
        self.assertEqual(payload["user"]["email"], self.email)
        self.assertTrue(response.headers.getlist("set-cookie"))
        self.sender.assert_not_called()

    def test_invalid_password_never_sends_verification(self):
        with self.assertRaises(HTTPException) as invalid:
            self._password_login(password="incorrect password")
        self.assertEqual(invalid.exception.status_code, 401)
        self.sender.assert_not_called()
        with self.factory() as db:
            user = db.scalar(select(User).where(User.email == self.email))
            self.assertIsNone(user.email_verification_token_hash)

    def test_legacy_passwordless_account_gets_passwordless_sign_in_guidance(self):
        legacy_email = f"magic-only-{uuid4().hex}@college.example"
        with self.factory() as db:
            db.add(User(
                username=legacy_email,
                email=legacy_email,
                role="viewer",
                active=True,
                password_hash="",
                is_email_verified=True,
                email_verified_at=datetime.now(timezone.utc),
            ))
            db.commit()
        with self.assertRaises(HTTPException) as result:
            controller.password_login(
                PasswordLoginIn(email=legacy_email, password="not-a-password"),
                make_request(),
                Response(),
            )
        self.assertEqual(result.exception.status_code, 409)
        self.assertIn("one-time email sign-in link", result.exception.detail)
        self.sender.assert_not_called()

    def test_smtp_delivery_failure_leaves_no_usable_token_or_session(self):
        self.sender.side_effect = EmailDeliveryError("SMTP delivery failed")
        with self.assertRaises(HTTPException) as failed:
            self._password_login()
        self.assertEqual(failed.exception.status_code, 503)
        with self.factory() as db:
            user = db.scalar(select(User).where(User.email == self.email))
            self.assertIsNone(user.email_verification_token_hash)
            self.assertIsNone(user.email_verification_expires_at)
            self.assertIsNone(db.scalar(select(AuthSession)))

    def test_verification_email_template_and_smtp_failure(self):
        raw_link = "https://navic.example/auth/verify-email?token=one-time-secret"
        text_body, html_body = emailer._verification_bodies(raw_link, 30, "Ada")
        self.assertIn("NavIC CBTMS", text_body)
        self.assertIn("Hello Ada", text_body)
        self.assertIn("Hello Ada", html_body)
        self.assertIn("30 minutes", text_body)
        self.assertIn("Verify email", html_body)
        self.assertIn(raw_link, html_body)
        with patch.dict("os.environ", {
            "APP_ENV": "development",
            "EMAIL_PROVIDER": "smtp",
            "SMTP_HOST": "mail.example.edu",
            "SMTP_PORT": "587",
            "SMTP_FROM_EMAIL": "no-reply@example.edu",
            "SMTP_USE_TLS": "false",
        }), patch.object(emailer.smtplib, "SMTP", side_effect=OSError("connection refused")):
            with self.assertRaises(EmailDeliveryError):
                emailer.send_verification_email(self.email, raw_link, 30)

    def test_console_email_backend_captures_registration_verification_safely(self):
        raw_link = "http://localhost:5173/auth/verify-email?token=single-use-test-token"
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "APP_ENV": "development",
            "EMAIL_PROVIDER": "console",
            "EMAIL_CAPTURE_FILE": f"{directory}/mail.jsonl",
        }):
            emailer.send_verification_email(self.email, raw_link, 30, first_name="Ada")
            with open(f"{directory}/mail.jsonl", encoding="utf-8") as capture_file:
                message = json.loads(capture_file.readline())
        self.assertEqual(message["to"], self.email)
        self.assertIn("Verify your NavIC CBTMS email address", message["subject"])
        self.assertIn("Hello Ada", message["text"])
        self.assertIn(raw_link, message["text"])
        self.assertIn("30 minutes", message["text"])

    def test_resend_replaces_old_token_and_obeys_cooldown(self):
        self._password_login()
        first = self._token_from_email()
        cooldown_response = Response()
        controller.resend_verification(
            ResendVerificationIn(email=self.email), make_request("127.0.0.43"), cooldown_response
        )
        self.assertEqual(cooldown_response.status_code, 202)
        self.assertEqual(self.sender.call_count, 1)
        with self.factory() as db:
            user = db.scalar(select(User).where(User.email == self.email))
            user.email_verification_sent_at = datetime.now(timezone.utc) - timedelta(seconds=61)
            db.commit()
        response = Response()
        result = controller.resend_verification(
            ResendVerificationIn(email=self.email), make_request("127.0.0.44"), response
        )
        self.assertEqual(response.status_code, 202)
        self.assertIn("email has been sent", result["message"])
        second = self._token_from_email()
        self.assertNotEqual(first, second)
        with self.assertRaises(HTTPException):
            controller.verify_email(VerifyEmailIn(token=first), make_request(), Response())
        controller.verify_email(VerifyEmailIn(token=second), make_request(), Response())

if __name__ == "__main__":
    unittest.main()
