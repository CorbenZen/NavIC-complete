# CBTMS Audit — 2026-11-15

Auditor pass over the roadmap implemented on branch `feature/cbtms-roadmap`.
Everything below is evidence from the working tree and from commands actually run.
The older 2026-11-06 audit is preserved at the bottom of this file.

## Baseline (Pass 0)

Environment: Linux, Python 3.15.2 (`.venv-local`), Node/Vite 8, SQLite `navic_dev.db`
(the `.env` default; no PostgreSQL server is available here).

| Check | Command | Result |
| --- | --- | --- |
| Python syntax | `python -m py_compile $(find navic_tcp backend tests -name '*.py')` | PASS (0 errors) |
| Backend + TCP tests | `python -m pytest backend/tests/ --ignore=backend/tests/test_magic_auth.py tests/ -q` | PASS 170 tests, 28 subtests |
| Lint | `python -m ruff check navic_tcp backend tests` | **FAIL 66 errors** |
| Frontend build | `cd frontend && npm run build` | PASS (pre-existing >500 kB chunk + lucide `use client` warnings) |
| Frontend lint / typecheck | n/a | no ESLint/TypeScript config exists in the repo |
| Backend boot | `PYTHONPATH=. python backend/python_uvicorn/run.py` | PASS, `/health` = `{"status":"ok","database":"ok","tcp":"listening"}` |
| Alembic | `alembic current` | DB stamped **0004**, head is **0006** |
| Alembic upgrade | `DATABASE_URL=sqlite:////tmp/... alembic upgrade head` on a DB copy | PASS (0004 → 0006) |

### Backups
- `backups/pre_audit_20261115_150308/` — rsync of the project (no `.git`, `node_modules`, `.venv*`, caches).
- `backups/pre_audit_20261115_150308.sqlite` — byte copy of `navic_dev.db`.
- `pg_dump` is not installed and the local database is SQLite, so no SQL dump was possible.

### Baseline failures found immediately
1. **Public share API is completely broken.** `navic_tcp/fastapi_app.py` uses `ShareToken`
   in 9 places but never imports it. `POST /api/buses/1/share` returns
   `500 Internal Server Error` (reproduced with `curl` against a live server).
2. **Geofences page crashes** — `markAllIncidentsRead` is referenced in JSX but never defined
   (`frontend/react-jsx/pages/fleet/Geofences.jsx:370`). Opening the incidents panel with unread
   items throws a `ReferenceError` and trips the error boundary.
3. **Share-link "Copy" produces a broken URL** — `Vehicles.jsx:661` passes `token.id` to
   `copyShareLink`, which builds `/public/bus/<numeric id>`. Only the newly created plaintext
   token can be copied; the list endpoint never returns it.
4. **Duplicate route handler names** in `fastapi_app.py` (`mark_incident_read`,
   `mark_all_incidents_read` defined for both alerts and geofences) plus dead code and unused
   imports — 66 ruff errors total.
5. **Geofence incident enrichment is wrong** — `db.get(TrackingDevice, inc.device_id)` treats the
   string `device_id` as the integer primary key, so device/vehicle columns never resolve.

_Details of every finding are added as the audit progresses._
