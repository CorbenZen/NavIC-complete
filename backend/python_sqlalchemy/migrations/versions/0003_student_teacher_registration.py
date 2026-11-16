"""Add student/teacher registration fields and normalized uniqueness rules.

Revision ID: 0003_student_teacher_registration
Revises: 0002_email_verification
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_student_teacher_registration"
down_revision = "0002_email_verification"
branch_labels = None
depends_on = None


def _columns(bind):
    return {column["name"] for column in sa.inspect(bind).get_columns("users")}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind)
    additions = (
        sa.Column("first_name", sa.String(length=80), nullable=True),
        sa.Column("last_name", sa.String(length=80), nullable=True),
        sa.Column("account_type", sa.String(length=16), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("users", column)

    if "created_at" in _columns(bind):
        op.execute(sa.text(
            "UPDATE users SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP) "
            "WHERE updated_at IS NULL"
        ))
    else:
        op.execute(sa.text("UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))

    duplicate_email = bind.execute(sa.text(
        "SELECT 1 FROM users GROUP BY lower(trim(email)) HAVING count(*) > 1 LIMIT 1"
    )).first()
    if duplicate_email:
        raise RuntimeError(
            "Cannot enforce normalized email uniqueness: duplicate case/whitespace-normalized emails exist. "
            "Resolve the duplicate accounts without deleting their data, then retry this migration."
        )

    if bind.dialect.name == "sqlite":
        # SQLAlchemy cannot reflect SQLite expression indexes, so inspect the
        # catalog directly (fresh databases already get them from model metadata).
        existing_indexes = set(bind.execute(sa.text(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='users'"
        )).scalars())
    else:
        existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("users")}
    if "uq_users_email_normalized" not in existing_indexes:
        op.create_index(
            "uq_users_email_normalized", "users", [sa.text("lower(trim(email))")], unique=True
        )
    if "uq_users_student_usn_normalized" not in existing_indexes:
        op.create_index(
            "uq_users_student_usn_normalized",
            "users",
            [sa.text("lower(trim(usn))")],
            unique=True,
            sqlite_where=sa.text("account_type = 'student' AND usn IS NOT NULL"),
            postgresql_where=sa.text("account_type = 'student' AND usn IS NOT NULL"),
        )

    if bind.dialect.name == "postgresql":
        checks = {constraint["name"] for constraint in sa.inspect(bind).get_check_constraints("users")}
        for name, condition in (
            ("ck_users_account_type", "account_type IS NULL OR account_type IN ('student', 'teacher')"),
            ("ck_users_student_usn_required", "account_type IS NULL OR account_type != 'student' OR usn IS NOT NULL"),
            ("ck_users_teacher_usn_null", "account_type IS NULL OR account_type != 'teacher' OR usn IS NULL"),
        ):
            if name not in checks:
                op.create_check_constraint(name, "users", condition)
    elif bind.dialect.name == "sqlite":
        # SQLite cannot add a CHECK constraint without rebuilding this legacy
        # table and its many foreign-key relationships, so equivalent triggers
        # enforce the registration invariants while preserving every row.
        for event in ("INSERT", "UPDATE"):
            suffix = event.lower()
            for name, condition, message in (
                ("account_type", "NEW.account_type IS NOT NULL AND NEW.account_type NOT IN ('student', 'teacher')", "invalid account type"),
                ("student_usn", "NEW.account_type = 'student' AND (NEW.usn IS NULL OR trim(NEW.usn) = '')", "student USN required"),
                ("teacher_usn", "NEW.account_type = 'teacher' AND NEW.usn IS NOT NULL", "teacher USN must be null"),
            ):
                trigger = f"trg_users_{name}_{suffix}"
                op.execute(sa.text(
                    f"CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE {event} ON users "
                    f"WHEN {condition} BEGIN SELECT RAISE(ABORT, '{message}'); END"
                ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        indexes = set(bind.execute(sa.text(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='users'"
        )).scalars())
    else:
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("users")}
    for name in ("uq_users_student_usn_normalized", "uq_users_email_normalized"):
        if name in indexes:
            op.drop_index(name, table_name="users")
    if bind.dialect.name == "sqlite":
        for event in ("insert", "update"):
            for check in ("account_type", "student_usn", "teacher_usn"):
                op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_users_{check}_{event}"))
    else:
        checks = {constraint["name"] for constraint in sa.inspect(bind).get_check_constraints("users")}
        for name in ("ck_users_teacher_usn_null", "ck_users_student_usn_required", "ck_users_account_type"):
            if name in checks:
                op.drop_constraint(name, "users", type_="check")
    columns = _columns(bind)
    for name in ("updated_at", "account_type", "last_name", "first_name"):
        if name in columns:
            op.drop_column("users", name)
