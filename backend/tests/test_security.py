"""Password hashing, JWT and login-limiter regression tests."""

import hashlib
import unittest
from unittest.mock import patch

from navic_tcp.security import (
    LoginRateLimiter,
    hash_password,
    issue_token,
    password_needs_rehash,
    verify_password,
    verify_token,
)


class PasswordTests(unittest.TestCase):
    def test_scrypt_hash_round_trip_and_rejects_wrong_password(self):
        stored = hash_password("correct horse battery staple")
        self.assertTrue(stored.startswith("scrypt$"))
        self.assertTrue(verify_password("correct horse battery staple", stored))
        self.assertFalse(verify_password("wrong password", stored))
        self.assertFalse(password_needs_rehash(stored))

    def test_legacy_sha256_hash_still_verifies_and_is_marked_for_rehash(self):
        legacy = hashlib.sha256(b"legacy-secret").hexdigest()
        self.assertTrue(verify_password("legacy-secret", legacy))
        self.assertFalse(verify_password("wrong", legacy))
        self.assertTrue(password_needs_rehash(legacy))
        self.assertFalse(verify_password("anything", None))
        self.assertFalse(verify_password("anything", "not-a-hash"))


class TokenTests(unittest.TestCase):
    secret = b"unit-test-secret"

    def test_issued_token_round_trips_with_claims(self):
        token = issue_token(self.secret, "admin@example.invalid", ttl_seconds=120)
        claims = verify_token(self.secret, token)
        self.assertEqual(claims["sub"], "admin@example.invalid")
        self.assertEqual(claims["iss"], "navic-cbtms")
        self.assertGreater(claims["exp"], claims["iat"])

    def test_token_with_wrong_secret_or_tampered_payload_is_rejected(self):
        token = issue_token(self.secret, "admin@example.invalid", ttl_seconds=120)
        with self.assertRaises(ValueError):
            verify_token(b"another-secret", token)
        header, payload, signature = token.split(".")
        with self.assertRaises(ValueError):
            verify_token(self.secret, f"{header}.{payload[:-1]}A.{signature}")

    def test_expired_token_is_rejected(self):
        token = issue_token(self.secret, "admin@example.invalid", ttl_seconds=-5)
        with self.assertRaises(ValueError):
            verify_token(self.secret, token)

    def test_missing_subject_is_rejected(self):
        with patch("navic_tcp.security.time.time", return_value=1_700_000_000):
            token = issue_token(self.secret, "", ttl_seconds=120)
        with self.assertRaises(ValueError):
            verify_token(self.secret, token)


class LoginRateLimiterTests(unittest.TestCase):
    def test_repeated_failures_block_then_reset(self):
        limiter = LoginRateLimiter(max_failures=2, window_seconds=300, cooldown_seconds=30)
        key = "127.0.0.1:admin@example.invalid"
        self.assertEqual(limiter.retry_after(key), 0)
        limiter.fail(key)
        self.assertEqual(limiter.retry_after(key), 0)
        limiter.fail(key)
        self.assertGreater(limiter.retry_after(key), 0)
        limiter.reset(key)
        self.assertEqual(limiter.retry_after(key), 0)


if __name__ == "__main__":
    unittest.main()
