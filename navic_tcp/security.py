"""Password hashing, JWT helpers and a small login rate limiter.

The JWT implementation is deliberately dependency-free (HS256) because the project
already used a hand-rolled token and adding an auth library is not required.  The
verify path checks the algorithm, signature, expiry and subject.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass, field

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    """Return a salted scrypt digest in a self-describing format."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Verify scrypt hashes and legacy unsalted SHA-256 hex digests."""
    if not stored:
        return False
    if stored.startswith("scrypt$"):
        try:
            _, n, r, p, salt, expected = stored.split("$", 5)
            digest = hashlib.scrypt(
                password.encode("utf-8"),
                salt=_unb64(salt),
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=len(_unb64(expected)),
            )
            return hmac.compare_digest(_b64(digest), expected)
        except (ValueError, TypeError):
            return False
    # Legacy development hash: sha256(password).hexdigest().
    if len(stored) == 64:
        try:
            int(stored, 16)
        except ValueError:
            return False
        return hmac.compare_digest(hashlib.sha256(password.encode("utf-8")).hexdigest(), stored)
    return False


def password_needs_rehash(stored: str | None) -> bool:
    return bool(stored) and not str(stored).startswith("scrypt$")


def new_secret(nbytes: int = 32) -> str:
    """Return a URL-safe cryptographically random token."""
    return secrets.token_urlsafe(nbytes)


def token_hash(raw: str) -> str:
    """Hash bearer/email tokens before storage; raw tokens never reach the DB."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _signature(secret: bytes, signing_input: str) -> str:
    return _b64(hmac.new(secret, signing_input.encode("ascii"), hashlib.sha256).digest())


def issue_token(secret: bytes, username: str, ttl_seconds: int = 3600) -> str:
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(
        json.dumps(
            {"sub": username, "iat": now, "nbf": now, "exp": now + int(ttl_seconds), "iss": "navic-cbtms"},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}"
    return f"{signing_input}.{_signature(secret, signing_input)}"


def verify_token(secret: bytes, token: str) -> dict:
    """Return claims or raise ValueError for any invalid/expired token."""
    try:
        header_b64, payload_b64, signature = token.split(".")
        header = json.loads(_unb64(header_b64))
        if header.get("alg") != "HS256":
            raise ValueError("unsupported algorithm")
        expected = _signature(secret, f"{header_b64}.{payload_b64}")
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        claims = json.loads(_unb64(payload_b64))
        now = time.time()
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise ValueError("missing subject")
        if float(claims.get("exp", 0)) < now:
            raise ValueError("expired")
        if float(claims.get("nbf", 0)) > now + 60:
            raise ValueError("not yet valid")
        return claims
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("invalid token") from exc


@dataclass
class _Bucket:
    failures: list[float] = field(default_factory=list)
    blocked_until: float = 0.0


class LoginRateLimiter:
    """In-process limiter: max attempts inside a window, then a cooldown."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 300, cooldown_seconds: int = 300):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        now = time.time()
        with self._lock:
            bucket = self._buckets.get(key)
            if not bucket:
                return 0
            if bucket.blocked_until > now:
                return max(1, int(bucket.blocked_until - now))
            bucket.failures = [stamp for stamp in bucket.failures if now - stamp < self.window_seconds]
            return 0

    def fail(self, key: str) -> None:
        now = time.time()
        with self._lock:
            bucket = self._buckets.setdefault(key, _Bucket())
            bucket.failures = [stamp for stamp in bucket.failures if now - stamp < self.window_seconds]
            bucket.failures.append(now)
            if len(bucket.failures) >= self.max_failures:
                bucket.blocked_until = now + self.cooldown_seconds
                bucket.failures.clear()

    def reset(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)


class SlidingWindowRateLimiter:
    """Count every request in a sliding window and report a retry delay.

    This is intentionally in-process. Multi-replica deployments should put the
    same policy in Redis (or a shared database) so limits are global.
    """

    def __init__(self, max_requests: int = 3, window_seconds: int = 600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.time()
        with self._lock:
            events = [stamp for stamp in self._events.get(key, []) if now - stamp < self.window_seconds]
            if len(events) >= self.max_requests:
                retry = max(1, int(self.window_seconds - (now - events[0])))
                self._events[key] = events
                return False, retry
            events.append(now)
            self._events[key] = events
            return True, 0

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

