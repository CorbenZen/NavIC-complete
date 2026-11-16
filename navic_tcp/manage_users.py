"""Controlled user provisioning for passwordless NavIC CBTMS accounts.

Examples:
    python -m navic_tcp.manage_users bootstrap-admin --email admin@college.edu
    python -m navic_tcp.manage_users bootstrap-admin --email another-admin@college.edu --user-id another-admin@college.edu --force
    python -m navic_tcp.manage_users create --email manager@college.edu --role transport
    python -m navic_tcp.manage_users create --email viewer@college.edu --role viewer --send-link
    python -m navic_tcp.manage_users list
    python -m navic_tcp.manage_users set-role --email viewer@college.edu --role transport

The application never grants administrator rights automatically to a new
sign-in. The first administrator must be created with this command (or the
development seed script).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timezone

from sqlalchemy import func, inspect, select

from . import auth as auth_service
from .env import load_env_file

# Load DATABASE_URL before importing db.py, which creates the engine at import
# time; otherwise provisioning could silently target the default local store.
load_env_file()

from .db import SessionLocal, engine
from .emailer import EmailConfigurationError, EmailDeliveryError, send_magic_link
from .models import User
from .security import hash_password

ROLES = ("admin", "transport", "viewer")


def _ensure_user_table() -> None:
    """Create only the account table when absent; provisioning must not backfill fleet data."""
    if not inspect(engine).has_table(User.__tablename__):
        User.__table__.create(bind=engine, checkfirst=True)


def _find(db, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == auth_service.normalize_email(email)))


def _send_link(db, user: User) -> None:
    raw, _expires = auth_service.create_magic_link(db, user, None)
    link = auth_service.build_verify_link(raw)
    send_magic_link(user.email, link, auth_service.magic_link_ttl_minutes())
    print(f"Sign-in email sent to {user.email}.")


def cmd_bootstrap_admin(args: argparse.Namespace) -> int:
    _ensure_user_table()
    email = auth_service.normalize_email(args.email)
    if not auth_service.valid_email(email):
        print("error: a valid --email is required", file=sys.stderr)
        return 2
    password = args.password
    if args.user_id and password is None:
        password = getpass.getpass("New administrator password: ")
        confirmation = getpass.getpass("Confirm administrator password: ")
        if password != confirmation:
            print("error: passwords do not match", file=sys.stderr)
            return 2
        if len(password) < 8 or not any(character.isalpha() for character in password):
            print("error: password must be at least 8 characters and include a letter", file=sys.stderr)
            return 2
    with SessionLocal() as db:
        existing = _find(db, email)
        if existing:
            if existing.role == "admin" and existing.active and not args.user_id and password is None:
                print(f"{email} is already an active administrator.")
                return 0
            existing.role = "admin"
            existing.active = True
            existing.is_email_verified = True
            existing.email_verified_at = existing.email_verified_at or datetime.now(timezone.utc)
            if args.user_id:
                normalized_user_id = args.user_id.strip().lower()
                collision = db.scalar(
                    select(User.id).where(
                        func.lower(func.trim(User.user_id)) == normalized_user_id,
                        User.id != existing.id,
                    )
                )
                if collision is not None:
                    print("error: that User ID is already assigned to another account", file=sys.stderr)
                    return 1
                existing.user_id = normalized_user_id
            if password is not None:
                existing.password_hash = hash_password(password)
            db.commit()
            print(f"Promoted existing account {email} to administrator.")
            return 0
        admin_exists = db.scalar(select(User).where(User.role == "admin", User.active.is_(True))) is not None
        if admin_exists and not args.force:
            print("error: an active administrator already exists; use --force to create another", file=sys.stderr)
            return 1
        user = User(
            username=args.username or email,
            email=email,
            user_id=args.user_id.strip().lower() if args.user_id else None,
            role="admin",
            password_hash=hash_password(password) if password else "",
            email_verified_at=datetime.now(timezone.utc),
            is_email_verified=True,
            active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Created administrator {user.email} (id={user.id}).")
        if args.send_link:
            _send_link(db, user)
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    _ensure_user_table()
    email = auth_service.normalize_email(args.email)
    if not auth_service.valid_email(email):
        print("error: a valid --email is required", file=sys.stderr)
        return 2
    if args.role not in ROLES:
        print(f"error: --role must be one of {', '.join(ROLES)}", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        existing = _find(db, email)
        if existing:
            print(f"error: an account already exists for {email}", file=sys.stderr)
            return 1
        user = User(
            username=args.username or email,
            email=email,
            role=args.role,
            password_hash=hash_password(args.password) if args.password else "",
            active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Created {user.role} account {user.email} (id={user.id}).")
        if args.send_link:
            _send_link(db, user)
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    _ensure_user_table()
    with SessionLocal() as db:
        users = list(db.scalars(select(User).order_by(User.id)).all())
    if not users:
        print("No users exist. Run bootstrap-admin first.")
        return 0
    print(f"{'ID':>4}  {'EMAIL':<38} {'ROLE':<10} {'ACTIVE':<6} LAST LOGIN")
    for user in users:
        last = user.last_login_at.isoformat() if user.last_login_at else "never"
        print(f"{user.id:>4}  {user.email:<38} {user.role:<10} {user.active!s:<6} {last}")
    return 0


def cmd_set_role(args: argparse.Namespace) -> int:
    _ensure_user_table()
    if args.role not in ROLES:
        print(f"error: --role must be one of {', '.join(ROLES)}", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        user = _find(db, args.email)
        if not user:
            print(f"error: no account for {args.email}", file=sys.stderr)
            return 1
        user.role = args.role
        db.commit()
        print(f"Set {user.email} role to {args.role}.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    _ensure_user_table()
    with SessionLocal() as db:
        user = _find(db, args.email)
        if not user:
            print(f"error: no account for {args.email}", file=sys.stderr)
            return 1
        user.active = args.active
        db.commit()
        print(f"{user.email} is now {'active' if user.active else 'inactive'}.")
    return 0


def cmd_invite(args: argparse.Namespace) -> int:
    _ensure_user_table()
    with SessionLocal() as db:
        user = _find(db, args.email)
        if not user or not user.active:
            print(f"error: no active account for {args.email}", file=sys.stderr)
            return 1
        try:
            _send_link(db, user)
        except EmailConfigurationError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except EmailDeliveryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provision NavIC CBTMS users safely")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap = sub.add_parser("bootstrap-admin", help="create or promote the first administrator")
    bootstrap.add_argument("--email", default=None, help="administrator email (or BOOTSTRAP_ADMIN_EMAIL)")
    bootstrap.add_argument("--username", default=None)
    bootstrap.add_argument("--user-id", default=None, help="optional login User ID for an additional administrator")
    bootstrap.add_argument(
        "--password",
        default=None,
        help="legacy option; avoid shell arguments, and prefer the secure prompt used with --user-id",
    )
    bootstrap.add_argument("--force", action="store_true", help="create another admin when one already exists")
    bootstrap.add_argument("--send-link", action="store_true")
    bootstrap.set_defaults(func=cmd_bootstrap_admin)

    create = sub.add_parser("create", help="create a transport manager or viewer")
    create.add_argument("--email", required=True)
    create.add_argument("--username", default=None)
    create.add_argument("--role", default="viewer", choices=ROLES)
    create.add_argument("--password", default=None, help="optional legacy password")
    create.add_argument("--send-link", action="store_true")
    create.set_defaults(func=cmd_create)

    listing = sub.add_parser("list", help="list accounts")
    listing.set_defaults(func=cmd_list)

    role = sub.add_parser("set-role", help="change an account role")
    role.add_argument("--email", required=True)
    role.add_argument("--role", required=True, choices=ROLES)
    role.set_defaults(func=cmd_set_role)

    activate = sub.add_parser("activate", help="enable an account")
    activate.add_argument("--email", required=True)
    activate.set_defaults(func=cmd_status, active=True)
    deactivate = sub.add_parser("deactivate", help="disable an account and its sign-in")
    deactivate.add_argument("--email", required=True)
    deactivate.set_defaults(func=cmd_status, active=False)

    invite = sub.add_parser("invite", help="email a fresh single-use sign-in link")
    invite.add_argument("--email", required=True)
    invite.set_defaults(func=cmd_invite)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "bootstrap-admin" and not args.email:
        import os

        args.email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
