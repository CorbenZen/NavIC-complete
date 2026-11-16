"""Add the User ID login identifier and make email optional.

Revision ID: 0004_user_id_password_auth
Revises: 0003_student_teacher_registration

Normal accounts now authenticate with a unique ``user_id`` and a hashed
password.  Email stays available for the administrator, Google and legacy
magic-link accounts, but it is no longer required for registration.

The migration is additive for data: existing rows are kept and receive a
deterministic ``USER<id>`` login identifier.  On SQLite the nullable email
change is performed through Alembic's batch table rebuild because SQLite cannot
drop a NOT NULL constraint in place; dependent triggers and indexes are
recreated afterwards.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_user_id_password_auth"
down_revision = "0003_student_teacher_registration"
branch_labels = None
depends_on = None

_EMAIL_INDEX = "uq_users_email_normalized"
_USER_ID_INDEX = "uq_users_user_id_normalized"
_USN_INDEX = "uq_users_student_usn_normalized"


def _columns(bind):
    return {column["name"] for column in sa.inspect(bind).get_columns("users")}


def _indexes(bind):
    if bind.dialect.name == "sqlite":
        return set(
            bind.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='users'")
            ).scalars()
        )
    return {index["name"] for index in sa.inspect(bind).get_indexes("users")}


def _email_is_not_null(bind) -> bool:
    for column in sa.inspect(bind).get_columns("users"):
        if column["name"] == "email":
            return column.get("nullable") is False
    return False


def _create_registration_indexes(bind) -> None:
    existing = _indexes(bind)
    if _USER_ID_INDEX not in existing:
        op.create_index(_USER_ID_INDEX, "users", [sa.text("lower(trim(user_id))")], unique=True)
    if _EMAIL_INDEX not in existing:
        op.create_index(_EMAIL_INDEX, "users", [sa.text("lower(trim(email))")], unique=True)
    if _USN_INDEX not in existing:
        op.create_index(
            _USN_INDEX,
            "users",
            [sa.text("lower(trim(usn))")],
            unique=True,
            sqlite_where=sa.text("account_type = 'student' AND usn IS NOT NULL"),
            postgresql_where=sa.text("account_type = 'student' AND usn IS NOT NULL"),
        )


def _create_sqlite_triggers(bind) -> None:
    if bind.dialect.name != "sqlite":
        return
    for event in ("INSERT", "UPDATE"):
        suffix = event.lower()
        for name, condition, message in (
            ("account_type", "NEW.account_type IS NOT NULL AND NEW.account_type NOT IN ('student', 'teacher')", "invalid account type"),
            ("student_usn", "NEW.account_type = 'student' AND (NEW.usn IS NULL OR trim(NEW.usn) = '')", "student USN required"),
            ("teacher_usn", "NEW.account_type = 'teacher' AND NEW.usn IS NOT NULL", "teacher USN must be null"),
        ):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER IF NOT EXISTS trg_users_{name}_{suffix} "
                    f"BEFORE {event} ON users WHEN {condition} "
                    f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
                )
            )


def upgrade() -> None:
    bind = op.get_bind()

    if "user_id" not in _columns(bind):
        op.add_column("users", sa.Column("user_id", sa.String(length=64), nullable=True))

    # Deterministic, unique, human-readable identifiers for pre-existing rows.
    op.execute(
        sa.text(
            "UPDATE users SET user_id = upper('USER' || id) "
            "WHERE user_id IS NULL OR trim(user_id) = ''"
        )
    )

    if _email_is_not_null(bind):
        if bind.dialect.name == "sqlite":
            # Batch mode rebuilds the table.  Dependent triggers/indexes are
            # recreated below, so drop the triggers first for a clean rebuild.
            for event in ("insert", "update"):
                for check in ("account_type", "student_usn", "teacher_usn"):
                    op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_users_{check}_{event}"))
            with op.batch_alter_table("users", recreate="always") as batch:
                batch.alter_column(
                    "email",
                    existing_type=sa.String(length=254),
                    nullable=True,
                )
        else:
            op.alter_column(
                "users",
                "email",
                existing_type=sa.String(length=254),
                nullable=True,
            )

    _create_registration_indexes(bind)
    _create_sqlite_triggers(bind)


def downgrade() -> None:
    bind = op.get_bind()
    existing = _indexes(bind)
    if _USER_ID_INDEX in existing:
        op.drop_index(_USER_ID_INDEX, table_name="users")

    # Restore NOT NULL only when every row has an address; otherwise the
    # downgrade would destroy account data and is refused.
    null_emails = bind.execute(sa.text("SELECT count(*) FROM users WHERE email IS NULL")).scalar()
    if not null_emails and _email_is_not_null(bind) is False:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("users", recreate="always") as batch:
                batch.alter_column(
                    "email",
                    existing_type=sa.String(length=254),
                    nullable=False,
                )
        else:
            op.alter_column(
                "users",
                "email",
                existing_type=sa.String(length=254),
                nullable=False,
            )

    if "user_id" in _columns(bind):
        op.drop_column("users", "user_id")
