"""Persist one-time email verification state on user accounts.

Revision ID: 0002_email_verification
Revises: 0001_baseline
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_email_verification"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    additions = (
        sa.Column("is_email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email_verification_token_hash", sa.String(length=64), nullable=True),
        sa.Column("email_verification_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_verification_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("users", column)

    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "email_verified_at" in columns:
        op.execute(
            sa.text(
                "UPDATE users SET is_email_verified = TRUE "
                "WHERE email_verified_at IS NOT NULL AND is_email_verified = FALSE"
            )
        )
    if bind.dialect.name == "sqlite":
        indexes = set(bind.execute(sa.text(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='users'"
        )).scalars())
    else:
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("users")}
    if "ix_users_email_verification_token_hash" not in indexes:
        op.create_index(
            "ix_users_email_verification_token_hash",
            "users",
            ["email_verification_token_hash"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        indexes = set(bind.execute(sa.text(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='users'"
        )).scalars())
    else:
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("users")}
    if "ix_users_email_verification_token_hash" in indexes:
        op.drop_index("ix_users_email_verification_token_hash", table_name="users")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    for name in (
        "email_verification_sent_at",
        "email_verification_expires_at",
        "email_verification_token_hash",
        "is_email_verified",
    ):
        if name in columns:
            op.drop_column("users", name)
