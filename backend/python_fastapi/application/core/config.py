"""Central runtime configuration for the NavIC backend.

All values come from the process environment (optionally loaded from the
project-root ``.env``).  Defaults match the existing development behaviour and
are applied to ``os.environ`` before the shared ``navic_tcp`` modules are
imported, so there is a single source of truth for both the website backend and
the embedded TCP receiver.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from navic_tcp.local_paths import default_database_url

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DEVICE_REGISTRY = PROJECT_ROOT / "config" / "devices.demo.json"
DEFAULT_FRONTEND_DIST = PROJECT_ROOT / "frontend" / "vite" / "build"
DEFAULT_DATABASE_URL = default_database_url()
DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if not raw:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def load_environment(path: str | Path | None = None) -> bool:
    """Load the project-root ``.env`` without overriding exported variables."""
    from navic_tcp.env import load_env_file

    return load_env_file(path or (PROJECT_ROOT / ".env"))


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the backend configuration."""

    project_root: Path = PROJECT_ROOT
    app_env: str = "development"
    database_url: str = DEFAULT_DATABASE_URL
    jwt_secret: str | None = None
    jwt_ttl_seconds: int = 3600
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    tcp_enabled: bool = True
    tcp_host: str = "127.0.0.1"
    tcp_port: int = 5000
    device_registry: Path = DEFAULT_DEVICE_REGISTRY
    email_provider: str = "console"
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"
    frontend_dist: Path = DEFAULT_FRONTEND_DIST
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    session_ttl_minutes: int = 720
    magic_link_ttl_minutes: int = 15
    demo_auth_bypass: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "info"

    @classmethod
    def from_environment(cls) -> Settings:
        app_env = os.getenv("APP_ENV", "development").strip().lower()
        is_development = app_env in {"development", "dev", "local"}
        api_port = _env_int("PORT", 8000)
        configured_backend_url = os.getenv("BACKEND_URL", "").strip()
        # In local development the same URL configures Uvicorn and the Vite
        # proxy, so a port change cannot silently split the two services.
        if is_development and configured_backend_url:
            configured_port = urlsplit(configured_backend_url).port
            if configured_port is not None:
                api_port = configured_port
        backend_url = (
            configured_backend_url
            or f"http://localhost:{api_port}"
        ).rstrip("/")
        return cls(
            app_env=app_env,
            database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL).strip(),
            jwt_secret=os.getenv("JWT_SECRET") or None,
            jwt_ttl_seconds=_env_int("JWT_TTL_SECONDS", 3600),
            cors_origins=_env_list("CORS_ORIGINS", DEFAULT_CORS_ORIGINS),
            tcp_enabled=_env_bool("TCP_ENABLED", True),
            tcp_host=os.getenv("TCP_HOST", "127.0.0.1"),
            tcp_port=_env_int("TCP_PORT", 5000),
            device_registry=Path(os.getenv("DEVICE_REGISTRY", str(DEFAULT_DEVICE_REGISTRY))),
            email_provider=os.getenv("EMAIL_PROVIDER", "console").strip().lower(),
            frontend_url=os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/"),
            backend_url=backend_url,
            frontend_dist=Path(os.getenv("FRONTEND_DIST", str(DEFAULT_FRONTEND_DIST))),
            cookie_secure=_env_bool("COOKIE_SECURE", not is_development),
            cookie_samesite=os.getenv(
                "COOKIE_SAMESITE", "lax" if is_development else "none"
            ).strip().lower(),
            session_ttl_minutes=_env_int("SESSION_TTL_MINUTES", 720),
            magic_link_ttl_minutes=_env_int("MAGIC_LINK_TTL_MINUTES", 20),
            demo_auth_bypass=_env_bool("DEMO_AUTH_BYPASS", False),
            api_host=os.getenv("API_HOST", "0.0.0.0"),
            api_port=api_port,
            log_level=os.getenv("LOG_LEVEL", "info").lower(),
        )

    @property
    def is_development(self) -> bool:
        return self.app_env in {"development", "dev", "local"}

    @property
    def websocket_url(self) -> str:
        parts = urlsplit(self.backend_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        return f"{scheme}://{parts.netloc}/ws/locations"

    def validate_production(self) -> None:
        """Fail startup when production is missing essential safety settings."""
        if self.is_development:
            return

        errors: list[str] = []
        if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
            errors.append("DATABASE_URL must point to persistent PostgreSQL in production")
        if not self.jwt_secret or len(self.jwt_secret) < 32:
            errors.append("JWT_SECRET must contain at least 32 characters in production")
        elif self.jwt_secret.lower().startswith(("replace-with", "change-me", "your-")):
            errors.append("JWT_SECRET must be replaced with a randomly generated secret")
        if len(os.getenv("AUTH_IP_SALT", "").strip()) < 32:
            errors.append("AUTH_IP_SALT must contain at least 32 characters in production")
        elif os.getenv("AUTH_IP_SALT", "").strip().lower().startswith(("replace-with", "change-me", "your-")):
            errors.append("AUTH_IP_SALT must be replaced with a randomly generated secret")
        if self.jwt_secret and self.jwt_secret == os.getenv("AUTH_IP_SALT", "").strip():
            errors.append("AUTH_IP_SALT must be different from JWT_SECRET")
        if self.demo_auth_bypass:
            errors.append("DEMO_AUTH_BYPASS must be disabled in production")
        if not self.frontend_url.startswith("https://"):
            errors.append("FRONTEND_URL must use HTTPS in production")
        if not self.backend_url.startswith("https://"):
            errors.append("BACKEND_URL or the provider's public service URL must use HTTPS in production")
        if not self.cors_origins or "*" in self.cors_origins:
            errors.append("CORS_ORIGINS must list explicit frontend origins")
        else:
            for origin in self.cors_origins:
                parsed_origin = urlsplit(origin)
                if parsed_origin.scheme != "https" or not parsed_origin.netloc or parsed_origin.path not in {"", "/"} or parsed_origin.query or parsed_origin.fragment:
                    errors.append("production CORS_ORIGINS must contain HTTPS origins only, without paths")
                    break
        if not self.cookie_secure:
            errors.append("COOKIE_SECURE must be true in production")
        if self.cookie_samesite != "none":
            errors.append("COOKIE_SAMESITE must be none when the frontend and API use separate HTTPS origins")

        admin_email = os.getenv("ADMIN_EMAIL", "").strip()
        admin_password_hash = os.getenv("ADMIN_PASSWORD_HASH", "").strip()
        if "@" not in admin_email or any(character.isspace() for character in admin_email):
            errors.append("ADMIN_EMAIL must be explicitly configured in production")
        if not admin_password_hash.startswith("scrypt$"):
            errors.append("ADMIN_PASSWORD_HASH must be a scrypt password hash in production")

        email_provider = self.email_provider.lower()
        if email_provider == "console":
            errors.append("EMAIL_PROVIDER must be smtp or resend in production")
        elif email_provider == "resend":
            if not os.getenv("EMAIL_API_KEY", "").strip():
                errors.append("EMAIL_API_KEY is required when EMAIL_PROVIDER=resend")
            if not (os.getenv("EMAIL_FROM", "").strip() or os.getenv("SMTP_FROM_EMAIL", "").strip()):
                errors.append("EMAIL_FROM or SMTP_FROM_EMAIL is required when EMAIL_PROVIDER=resend")
        elif email_provider == "smtp":
            for key in ("SMTP_HOST",):
                if not os.getenv(key, "").strip():
                    errors.append(f"{key} is required when EMAIL_PROVIDER=smtp")
            if not (os.getenv("SMTP_FROM_EMAIL", "").strip() or os.getenv("EMAIL_FROM", "").strip()):
                errors.append("SMTP_FROM_EMAIL or EMAIL_FROM is required when EMAIL_PROVIDER=smtp")
        elif email_provider not in {"smtp", "resend"}:
            errors.append("EMAIL_PROVIDER must be smtp or resend in production")

        if errors:
            raise RuntimeError("Invalid production configuration: " + "; ".join(errors))

    def apply_defaults(self) -> None:
        """Publish settings as environment defaults for the shared modules.

        ``os.environ.setdefault`` means an explicit export or a ``.env`` value
        always wins.  Only values that the shared ``navic_tcp`` modules read at
        import time are published here.
        """
        defaults = {
            "APP_ENV": self.app_env,
            "DATABASE_URL": self.database_url,
            "CORS_ORIGINS": ",".join(self.cors_origins),
            "FRONTEND_URL": self.frontend_url,
            "BACKEND_URL": self.backend_url,
            "FRONTEND_DIST": str(self.frontend_dist),
            "DEVICE_REGISTRY": str(self.device_registry),
            "EMAIL_PROVIDER": self.email_provider,
            "TCP_HOST": self.tcp_host,
            "TCP_PORT": str(self.tcp_port),
            "COOKIE_SECURE": "true" if self.cookie_secure else "false",
            "COOKIE_SAMESITE": self.cookie_samesite,
        }
        for key, value in defaults.items():
            os.environ.setdefault(key, value)
        os.environ.setdefault("TCP_ENABLED", "true" if self.tcp_enabled else "false")
        if self.jwt_secret:
            os.environ.setdefault("JWT_SECRET", self.jwt_secret)
        if self.demo_auth_bypass:
            os.environ.setdefault("DEMO_AUTH_BYPASS", "true")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings snapshot for the current process."""
    return Settings.from_environment()
