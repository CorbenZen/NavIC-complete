# Backend migrations

Schema changes are managed with **Alembic**. Run them from the repository root:

```bash
PYTHONPATH=. .venv-local/bin/python -m alembic -c backend/alembic.ini current
PYTHONPATH=. .venv-local/bin/python -m alembic -c backend/alembic.ini upgrade head
```

The revision chain lives in `backend/python_sqlalchemy/migrations/versions/`.
`0007_roadmap_tables` adds alert incidents, geofence incidents, share tokens and
the `location_history.data_source` provenance column.

The application also runs `navic_tcp.schema.ensure_schema` on startup. That path
is additive only (create missing tables / add missing nullable columns) so older
development databases keep working without a manual migration.

The hand-written `002_*` / `003_*` scripts that used to live in this folder are
superseded by revision `0007` and were moved to
`_archive/20261115_audit/backend/migrations/` during the 2026-11-15 audit. They
are kept for reference only and must not be run.
