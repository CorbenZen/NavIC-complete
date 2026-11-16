"""Email delivery for passwordless sign-in links.

Supported providers:

* ``resend``  - HTTPS API, no extra Python dependency (recommended for production).
* ``smtp``    - any transactional SMTP provider or Gmail app-password SMTP.
* ``console`` - development only; writes messages to a local capture file.

No credentials are hardcoded.  Raw sign-in tokens are never written to the
application log; the development capture file is the only place a full link is
stored, and it refuses to operate outside development mode.
"""

from __future__ import annotations

import contextlib
import html
import json
import logging
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

LOG = logging.getLogger("navic_tcp.email")


class EmailConfigurationError(RuntimeError):
    """Raised when email delivery is requested without usable configuration."""


class EmailDeliveryError(RuntimeError):
    """Raised when a provider rejects a message; callers must not leak details."""


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_development() -> bool:
    return os.getenv("APP_ENV", "production").strip().lower() in {"development", "dev", "local"}


def provider_name() -> str:
    explicit = os.getenv("EMAIL_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("SMTP_HOST"):
        return "smtp"
    return "console" if is_development() else ""


def from_address() -> str:
    return (
        os.getenv("SMTP_FROM_EMAIL", "").strip()
        or os.getenv("EMAIL_FROM", "").strip()
        or "NavIC CBTMS <no-reply@localhost>"
    )


def capture_file() -> Path:
    return Path(os.getenv("EMAIL_CAPTURE_FILE", "dev-mail.jsonl")).expanduser()


def delivery_status() -> dict:
    """Safe status for /api/meta; never includes secrets."""
    provider = provider_name()
    configured = False
    if provider == "resend":
        configured = bool(os.getenv("EMAIL_API_KEY")) and bool(os.getenv("EMAIL_FROM"))
    elif provider == "smtp":
        configured = bool(os.getenv("SMTP_HOST")) and bool(
            os.getenv("SMTP_FROM_EMAIL") or os.getenv("EMAIL_FROM")
        )
    elif provider == "console":
        configured = is_development()
    return {
        "provider": provider or "unconfigured",
        "configured": configured,
        "capture_file": str(capture_file()) if provider == "console" and is_development() else None,
    }


def _subject() -> str:
    return "Your NavIC CBTMS sign-in link"


def _verification_subject() -> str:
    return "Verify your NavIC CBTMS email address"


def _bodies(link: str, expires_minutes: int) -> tuple[str, str]:
    text = (
        "Sign in to NavIC CBTMS\n\n"
        f"Open this single-use link within {expires_minutes} minutes:\n{link}\n\n"
        "If you did not request this email, you can ignore it. The link expires after one use. "
        "Never forward it to anyone.\n"
    )
    safe_link = html.escape(link, quote=True)
    body = f"""\
<!doctype html>
<html><body style="margin:0;padding:0;background:#f4f7f6;font-family:Arial,Helvetica,sans-serif;color:#0f172a">
  <div style="max-width:560px;margin:32px auto;background:#ffffff;border:1px solid #dbe5e1;border-radius:14px;overflow:hidden">
    <div style="background:#0f766e;padding:22px 28px;color:#ffffff">
      <div style="font-size:20px;font-weight:700;letter-spacing:.3px">NavIC CBTMS</div>
      <div style="font-size:13px;opacity:.85;margin-top:3px">College Bus Tracking &amp; Management</div>
    </div>
    <div style="padding:28px">
      <h1 style="font-size:20px;margin:0 0 12px">Sign in to your account</h1>
      <p style="font-size:14px;line-height:1.65;color:#475569">
        Use the button below to sign in. This link is single-use and expires in
        <strong>{expires_minutes} minutes</strong>.
      </p>
      <p style="margin:24px 0">
        <a href="{safe_link}" style="display:inline-block;background:#0f766e;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:9px;font-weight:600;font-size:14px">Continue to NavIC</a>
      </p>
      <p style="font-size:12px;line-height:1.6;color:#64748b">
        If the button does not work, copy this address into your browser:<br>
        <span style="word-break:break-all;color:#0f766e">{safe_link}</span>
      </p>
      <p style="font-size:12px;line-height:1.6;color:#64748b;margin-top:22px">
        If you did not request this email, ignore it. Never forward this link to anyone.
      </p>
    </div>
  </div>
</body></html>
"""
    return text, body


def _verification_bodies(link: str, expires_minutes: int, first_name: str = "") -> tuple[str, str]:
    greeting = f"Hello {first_name.strip()}," if first_name and first_name.strip() else "Hello,"
    safe_greeting = html.escape(greeting)
    text = (
        f"{greeting}\n\n"
        "Verify your NavIC CBTMS email address\n\n"
        f"Open this one-time link within {expires_minutes} minutes to verify your email:\n{link}\n\n"
        "If you did not request this verification, ignore this message. Do not forward the link.\n"
    )
    safe_link = html.escape(link, quote=True)
    body = f"""\
<!doctype html>
<html><body style="margin:0;padding:0;background:#f4f7f6;font-family:Arial,Helvetica,sans-serif;color:#0f172a">
  <div style="max-width:560px;margin:32px auto;background:#ffffff;border:1px solid #dbe5e1;border-radius:14px;overflow:hidden">
    <div style="background:#0f766e;padding:22px 28px;color:#ffffff">
      <div style="font-size:20px;font-weight:700;letter-spacing:.3px">NavIC CBTMS</div>
      <div style="font-size:13px;opacity:.85;margin-top:3px">College Bus Tracking &amp; Management</div>
    </div>
    <div style="padding:28px">
      <p style="font-size:14px">{safe_greeting}</p>
      <h1 style="font-size:20px;margin:0 0 12px">Verify your email address</h1>
      <p style="font-size:14px;line-height:1.65;color:#475569">Confirm this address to finish securing your NavIC account. The link expires in <strong>{expires_minutes} minutes</strong> and can only be used once.</p>
      <p style="margin:24px 0"><a href="{safe_link}" style="display:inline-block;background:#0f766e;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:9px;font-weight:600;font-size:14px">Verify email</a></p>
      <p style="font-size:12px;line-height:1.6;color:#64748b">If the button does not work, copy this address into your browser:<br><span style="word-break:break-all;color:#0f766e">{safe_link}</span></p>
      <p style="font-size:12px;line-height:1.6;color:#64748b;margin-top:22px">If you did not request this verification, ignore this email. Your account will remain unchanged. Never forward this link.</p>
    </div>
  </div>
</body></html>
"""
    return text, body


def _send_resend(to_email: str, text: str, body: str, subject: str | None = None) -> None:
    api_key = os.getenv("EMAIL_API_KEY", "").strip()
    if not api_key:
        raise EmailConfigurationError("EMAIL_API_KEY is not configured")
    payload = {
        "from": from_address(),
        "to": [to_email],
        "subject": subject or _subject(),
        "text": text,
        "html": body,
    }
    request = urllib.request.Request(
        os.getenv("RESEND_API_URL", "https://api.resend.com/emails"),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "navic-cbtms/2",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if not 200 <= response.status < 300:
                raise EmailDeliveryError(f"resend returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        raise EmailDeliveryError(f"resend returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise EmailDeliveryError("resend could not be reached") from exc


def _send_smtp(to_email: str, text: str, body: str, subject: str | None = None) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    if not host:
        raise EmailConfigurationError("SMTP_HOST is not configured")
    port = int(os.getenv("SMTP_PORT", "587"))
    message = EmailMessage()
    message["From"] = from_address()
    message["To"] = to_email
    message["Subject"] = subject or _subject()
    message.set_content(text)
    message.add_alternative(body, subtype="html")

    timeout = float(os.getenv("SMTP_TIMEOUT_SECONDS", "15"))
    use_ssl = _env_bool("SMTP_SSL", port == 465)
    use_tls = _env_bool("SMTP_USE_TLS", _env_bool("SMTP_STARTTLS", True))
    if not is_development() and not (use_ssl or use_tls):
        raise EmailConfigurationError("SMTP TLS is required outside development")
    context = ssl.create_default_context()
    try:
        if use_ssl:
            client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)
        with client:
            client.ehlo()
            if not use_ssl and use_tls:
                client.starttls(context=context)
                client.ehlo()
            username = os.getenv("SMTP_USERNAME", "").strip()
            password = os.getenv("SMTP_PASSWORD", "")
            if username:
                client.login(username, password)
            client.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailDeliveryError("SMTP delivery failed") from exc


def _send_console(to_email: str, text: str, body: str, subject: str | None = None) -> None:
    if not is_development():
        raise EmailConfigurationError("the console email provider is development-only")
    path = capture_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "to": to_email,
        "subject": subject or _subject(),
        "text": text,
        "html": body,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    LOG.info("development email captured for %s at %s", to_email, path)


def send_magic_link(to_email: str, link: str, expires_minutes: int) -> None:
    """Deliver one sign-in email or raise a configuration/delivery error."""
    provider = provider_name()
    text, body = _bodies(link, expires_minutes)
    if provider == "resend":
        _send_resend(to_email, text, body)
    elif provider == "smtp":
        _send_smtp(to_email, text, body)
    elif provider == "console":
        _send_console(to_email, text, body)
    else:
        raise EmailConfigurationError("no EMAIL_PROVIDER is configured")


def send_verification_email(to_email: str, link: str, expires_minutes: int, *, first_name: str = "") -> None:
    """Deliver an email-verification message through the configured provider."""
    provider = provider_name()
    text, body = _verification_bodies(link, expires_minutes, first_name)
    subject = _verification_subject()
    if provider == "resend":
        _send_resend(to_email, text, body, subject)
    elif provider == "smtp":
        _send_smtp(to_email, text, body, subject)
    elif provider == "console":
        _send_console(to_email, text, body, subject)
    else:
        raise EmailConfigurationError("no EMAIL_PROVIDER is configured")
