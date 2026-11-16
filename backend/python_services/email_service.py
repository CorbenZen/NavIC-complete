"""Email delivery service.

Magic-link delivery uses the existing provider abstraction in
``navic_tcp.emailer`` (console capture, Resend or SMTP).
"""

from __future__ import annotations

from typing import Any

from navic_tcp.emailer import (
    EmailConfigurationError,
    EmailDeliveryError,
    delivery_status,
    from_address,
    provider_name,
    send_magic_link,
    send_verification_email,
)


def send_magic_link_email(to_email: str, link: str, expires_minutes: int) -> None:
    """Deliver a magic sign-in link with the configured provider."""
    send_magic_link(to_email, link, expires_minutes)


def send_email_verification(to_email: str, link: str, expires_minutes: int, *, first_name: str = "") -> None:
    """Send the one-time account-verification email through the configured provider."""
    send_verification_email(to_email, link, expires_minutes, first_name=first_name)


def email_status() -> dict[str, Any]:
    """Return the non-secret delivery status used by ``/api/meta``."""
    return delivery_status()


__all__ = [
    "EmailConfigurationError",
    "EmailDeliveryError",
    "email_status",
    "from_address",
    "provider_name",
    "send_email_verification",
    "send_magic_link_email",
]
