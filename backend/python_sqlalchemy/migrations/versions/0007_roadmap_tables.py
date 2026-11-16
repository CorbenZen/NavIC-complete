"""Roadmap schema: alert incidents, geofence incidents, share tokens, provenance.

Revision ID: 0007_roadmap_tables
Revises: 0006_legacy_nullable_timestamps

Everything here is additive and guarded with ``checkfirst``/column inspection so
it is safe on databases that already received the equivalent tables from
``navic_tcp.schema.ensure_schema`` (the application's startup upgrade path).
Downgrades drop only what this revision created. Column removal is skipped on
SQLite, which cannot drop columns in older versions; the columns are nullable
and harmless if left behind.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_roadmap_tables"
down_revision = "0006_legacy_nullable_timestamps"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_postgres = bind.dialect.name == "postgresql"

    if not inspector.has_table("alert_incidents"):
        op.create_table(
            "alert_incidents",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "device_id",
                sa.String(length=64),
                sa.ForeignKey("tracking_devices.device_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("event_type", sa.String(length=40), nullable=False, server_default="device_offline"),
            sa.Column("state", sa.String(length=20), nullable=False, server_default="open"),
            sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("alert_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_alert_incidents_device_id", "alert_incidents", ["device_id"])
        op.create_index("ix_alert_incidents_event_type", "alert_incidents", ["event_type"])
        op.create_index("ix_alert_incidents_state", "alert_incidents", ["state"])
        op.create_index("ix_alert_incidents_opened_at", "alert_incidents", ["opened_at"])
        op.create_index("ix_alert_incidents_is_read", "alert_incidents", ["is_read"])
        op.create_index("ix_alert_incidents_created_at", "alert_incidents", ["created_at"])

    if not inspector.has_table("geofence_incidents"):
        op.create_table(
            "geofence_incidents",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "device_id",
                sa.String(length=64),
                sa.ForeignKey("tracking_devices.device_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "geofence_id",
                sa.Integer(),
                sa.ForeignKey("geofences.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("state", sa.String(length=20), nullable=False),
            sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_geofence_incidents_device_id", "geofence_incidents", ["device_id"])
        op.create_index("ix_geofence_incidents_geofence_id", "geofence_incidents", ["geofence_id"])
        op.create_index("ix_geofence_incidents_state", "geofence_incidents", ["state"])
        op.create_index("ix_geofence_incidents_transitioned_at", "geofence_incidents", ["transitioned_at"])
        op.create_index("ix_geofence_incidents_is_read", "geofence_incidents", ["is_read"])
        op.create_index("ix_geofence_incidents_created_at", "geofence_incidents", ["created_at"])

    if not inspector.has_table("share_tokens"):
        op.create_table(
            "share_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("bus_id", sa.Integer(), sa.ForeignKey("buses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=True),
            sa.Column(
                "created_by",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_share_tokens_bus_id", "share_tokens", ["bus_id"])
        op.create_index("ix_share_tokens_token_hash", "share_tokens", ["token_hash"], unique=True)
        op.create_index("ix_share_tokens_created_at", "share_tokens", ["created_at"])
        op.create_index("ix_share_tokens_expires_at", "share_tokens", ["expires_at"])

    # Nullable/additive columns added by the roadmap.
    if inspector.has_table("alerts"):
        # SQLite cannot ALTER TABLE ... ADD CONSTRAINT, so the foreign key is
        # declared only on engines that support it. The application validates
        # incident ownership; this is an integrity hint, not the only guard.
        incident_column = (
            sa.Column(
                "incident_id",
                sa.Integer(),
                sa.ForeignKey("alert_incidents.id", ondelete="SET NULL"),
                nullable=True,
            )
            if is_postgres
            else sa.Column("incident_id", sa.Integer(), nullable=True)
        )
        _add_column("alerts", incident_column)
        if "incident_id" in _columns("alerts"):
            op.execute("CREATE INDEX IF NOT EXISTS ix_alerts_incident_id ON alerts (incident_id)")

    if inspector.has_table("device_geofence_state"):
        _add_column("device_geofence_state", sa.Column("consecutive_inside", sa.Integer(), nullable=False, server_default="0"))
        _add_column("device_geofence_state", sa.Column("consecutive_outside", sa.Integer(), nullable=False, server_default="0"))

    if inspector.has_table("location_history"):
        _add_column(
            "location_history",
            sa.Column("data_source", sa.String(length=24), nullable=False, server_default="hardware"),
        )
        if "simulated" in _columns("location_history"):
            # Backfill only empty values; never relabel an explicit source.
            op.execute(
                "UPDATE location_history SET data_source = CASE "
                + ("WHEN simulated = TRUE THEN 'simulator' ELSE 'hardware' END " if is_postgres else "WHEN simulated = 1 THEN 'simulator' ELSE 'hardware' END ")
                + "WHERE data_source IS NULL OR trim(data_source) = ''"
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_postgres = bind.dialect.name == "postgresql"

    if inspector.has_table("share_tokens"):
        op.drop_table("share_tokens")

    if inspector.has_table("geofence_incidents"):
        op.drop_table("geofence_incidents")

    if inspector.has_table("alert_incidents"):
        # Remove the FK column first on engines that support it.
        if "incident_id" in _columns("alerts") and is_postgres:
            op.drop_column("alerts", "incident_id")
        op.drop_table("alert_incidents")

    if is_postgres:
        for table, column in (
            ("location_history", "data_source"),
            ("device_geofence_state", "consecutive_inside"),
            ("device_geofence_state", "consecutive_outside"),
        ):
            if column in _columns(table):
                op.drop_column(table, column)
