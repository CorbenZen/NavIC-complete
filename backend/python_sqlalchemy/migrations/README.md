# Database migrations

NavIC keeps **one declarative schema** in `navic_tcp/models.py`. The website and
the TCP application import the same `Base` and metadata.

Two complementary mechanisms manage that schema:

1. **Startup additive upgrades** — `navic_tcp.schema.ensure_schema` creates
   missing tables and adds missing nullable columns. It runs on every FastAPI
   lifespan start and via `backend.python_sqlalchemy.database.init_database()`. It never drops
   or rewrites data.
2. **Alembic revisions** — `backend/alembic.ini` and
   `backend/python_sqlalchemy/migrations/` provide a versioned migration history for deployments
  that require one. The baseline creates the shared metadata; subsequent
  revisions add verification state and student/teacher registration fields.
  Revision 0003 refuses normalized email duplicates before adding the unique
  expression index. Existing user rows keep their account type unset.

The application does **not** depend on Alembic at runtime. If Alembic is not
installed, startup and `ensure_schema` continue to work.

## Commands

Run from `backend/`:

```bash
alembic upgrade head
alembic current
alembic history
```

Use an explicit database for a rehearsal:

```bash
DATABASE_URL=sqlite:////tmp/navic-migration-test.db alembic upgrade head
```

Generate a future revision:

```bash
alembic revision --autogenerate -m "describe the additive change"
```

Review generated SQL for both SQLite and PostgreSQL before applying it. The
environment uses `render_as_batch=True` for SQLite and `compare_type=True`.

## Deploying to an existing database

`alembic upgrade head` on a database that already contains the NavIC tables is
safe: `Base.metadata.create_all` is check-first, so nothing is recreated, and
Alembic stamps `0001_baseline` as the current revision. Back up the database
before any schema operation.

`alembic downgrade base` drops the tables created by the baseline. Do not run it
against production data.
