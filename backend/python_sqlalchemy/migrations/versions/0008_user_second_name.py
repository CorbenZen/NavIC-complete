"""Add the explicit second-name field used by ID-based accounts.

Revision ID: 0008_user_second_name
Revises: 0007_roadmap_tables

Existing names are copied from ``last_name``; both fields remain available for
older profile consumers. Downgrade removes only this additive column.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_user_second_name"
down_revision = "0007_roadmap_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "second_name" not in columns:
        op.add_column("users", sa.Column("second_name", sa.String(length=80), nullable=True))
        op.execute("UPDATE users SET second_name = last_name WHERE second_name IS NULL")


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "second_name" in columns:
        op.drop_column("users", "second_name")
