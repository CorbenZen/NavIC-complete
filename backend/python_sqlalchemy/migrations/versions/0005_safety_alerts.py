"""Restore the existing safety alerts table to shared SQLAlchemy metadata.

Revision ID: 0005_safety_alerts
Revises: 0004_user_id_password_auth

The local database already contains SOS/safety alert records, but the model had
been omitted from metadata. Keep the table and its existing rows intact while
ensuring fresh PostgreSQL installations receive the same schema.
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_safety_alerts"
down_revision = "0004_user_id_password_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("safety_alerts"):
        op.create_table(
            "safety_alerts",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("bus_id", sa.Integer(), sa.ForeignKey("buses.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("location_source", sa.String(length=24), nullable=False),
            sa.Column("reason", sa.String(length=48), nullable=False),
            sa.Column("description", sa.String(length=2000), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("acknowledged_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolution_notes", sa.String(length=2000), nullable=True),
            sa.Column("idempotency_key", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("idempotency_key", name="uq_safety_alerts_idempotency_key"),
        )
        for name, columns in (
            ("ix_safety_alerts_created_at", ["created_at"]),
            ("ix_safety_alerts_reason", ["reason"]),
            ("ix_safety_alerts_status", ["status"]),
            ("ix_safety_bus_status", ["bus_id", "status"]),
            ("ix_safety_alerts_bus_id", ["bus_id"]),
            ("ix_safety_status_created", ["status", "created_at"]),
            ("ix_safety_alerts_user_id", ["user_id"]),
        ):
            op.create_index(name, "safety_alerts", columns)


def downgrade() -> None:
    # A downgrade removes safety records. Back up the database before running.
    if sa.inspect(op.get_bind()).has_table("safety_alerts"):
        op.drop_table("safety_alerts")
