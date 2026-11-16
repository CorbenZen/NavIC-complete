"""Baseline NavIC schema.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-13

The baseline uses the shared declarative metadata instead of duplicating 19
table definitions.  On a fresh database it creates the complete schema; on an
existing database every ``create_all`` check is a no-op and Alembic records the
revision.  Additive column upgrades remain owned by
``navic_tcp.schema.ensure_schema`` and run on application startup.
"""

from __future__ import annotations

from alembic import op

from navic_tcp.models import Base

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # A baseline downgrade removes the tables this revision created.  Back up
    # the database before running it; application data is not preserved.
    Base.metadata.drop_all(bind=op.get_bind())
