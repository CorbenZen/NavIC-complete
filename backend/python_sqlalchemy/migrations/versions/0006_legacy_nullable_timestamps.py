"""Preserve nullable legacy timestamps while importing existing records.

Revision ID: 0006_legacy_nullable_timestamps
Revises: 0005_safety_alerts

The SQLite database contains historical NULL timestamps in these columns.
Allowing NULL preserves those original records during a PostgreSQL migration.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_legacy_nullable_timestamps"
down_revision = "0005_safety_alerts"
branch_labels = None
depends_on = None

_COLUMNS = {
    "buses": ("created_at",),
    "tracking_devices": ("created_at",),
    "users": ("created_at",),
    "drivers": ("created_at",),
    "routes": ("created_at",),
}


def upgrade() -> None:
    bind = op.get_bind()
    for table_name, column_names in _COLUMNS.items():
        existing = {column["name"]: column for column in sa.inspect(bind).get_columns(table_name)}
        for column_name in column_names:
            column = existing.get(column_name)
            if column is None or column.get("nullable", True):
                continue
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table(table_name, recreate="always") as batch:
                    batch.alter_column(
                        column_name,
                        existing_type=column["type"],
                        nullable=True,
                    )
            else:
                op.alter_column(
                    table_name,
                    column_name,
                    existing_type=column["type"],
                    nullable=True,
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Restore the older constraint only when every preserved row satisfies it.
    # A nullable legacy timestamp is data; refusing that downgrade is safer than
    # replacing it with a fabricated timestamp or deleting the row.
    for table_name, column_names in _COLUMNS.items():
        if not inspector.has_table(table_name):
            continue
        existing = {column["name"]: column for column in inspector.get_columns(table_name)}
        for column_name in column_names:
            column = existing.get(column_name)
            if column is None or not column.get("nullable", True):
                continue
            null_count = bind.execute(
                sa.text(f'SELECT COUNT(*) FROM "{table_name}" WHERE "{column_name}" IS NULL')
            ).scalar_one()
            if null_count:
                raise RuntimeError(
                    f"Cannot restore NOT NULL on {table_name}.{column_name}: "
                    f"{null_count} preserved row(s) have no timestamp."
                )
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table(table_name, recreate="always") as batch:
                    batch.alter_column(
                        column_name,
                        existing_type=column["type"],
                        nullable=False,
                    )
            else:
                op.alter_column(
                    table_name,
                    column_name,
                    existing_type=column["type"],
                    nullable=False,
                )
