# Verification log

Date: 2026-11-15. This file records commands run in this Codex session. Earlier reports were not treated as evidence.

## Commands and results

```text
python -m compileall -q backend navic_tcp tests && echo 'py_compile: PASS'
py_compile: PASS
```

```text
cd frontend && npm run check
FAIL: lint gate reported 38 errors and 44 warnings; build did not run through this command.
```

```text
cd frontend && npm run build
vite v8.3.6 building client environment for production...
✓ 2169 modules transformed.
vite/build/index.html 1.30 kB │ gzip: 0.64 kB
vite/build/assets/index-BdCmCAHl.css 98.78 kB │ gzip: 22.64 kB
vite/build/assets/index-BBWCq_Ot.js 677.44 kB │ gzip: 195.98 kB
✓ built in 813ms
```

```text
./.venv-local/bin/ruff check .
Found 91 errors.
```

```text
./.venv-local/bin/ruff check scripts/replay_nmea.py --fix
Found 8 errors (8 fixed, 0 remaining).
./.venv-local/bin/ruff check scripts/replay_nmea.py
All checks passed!
```

```text
python -m compileall -q backend navic_tcp tests
py_compile: PASS
./.venv-local/bin/ruff check backend navic_tcp tests scripts
All checks passed!
```

```text
./.venv-local/bin/pytest -q
17 collection errors, all import-file mismatches caused by duplicate test modules under backups/ and tests/.
```

```text
./.venv-local/bin/pytest -vv -x backend/tests tests
collected 207 items
13 passed; stalled at backend/tests/test_backend_app.py::ApplicationCompositionTests::test_every_shared_route_is_registered; process stopped.
```

```text
./.venv-local/bin/alembic -c backend/alembic.ini current
SQLite; current revision: 0004_user_id_password_auth
```

```text
DATABASE_URL=sqlite:////tmp/navic_codex_migrations.sqlite3 ./.venv-local/bin/alembic -c backend/alembic.ini upgrade head
PASS: revisions 0001 through 0007 applied on scratch SQLite database.
```

```text
DATABASE_URL=sqlite:////tmp/navic_codex_migrations.sqlite3 ./.venv-local/bin/alembic -c backend/alembic.ini downgrade base
FAIL: SQLite error while dropping users.user_id in 0004; index ix_users_user_id still refers to the column.
```

```text
APP_ENV=development DEMO_AUTH_BYPASS=true TCP_ENABLED=false ./.venv-local/bin/python backend/run.py
FAIL against configured DB: startup backfill got sqlite3.OperationalError: attempt to write a readonly database.
PASS against isolated /tmp/navic_codex_smoke.sqlite3; startup completed, then process was stopped.
```

Browser smoke test, route/theme matrix, interactions, backend logs after browser testing, fresh clone README procedure, and current DB migration: **NOT TESTED**. Vite listen returned `EPERM` in the sandbox and port 5173 was already in use during the escalated retry. `pg_dump` was unavailable; the project’s configured storage is SQLite. No database contents were changed by these checks.

## Live tracking follow-up

```text
npx eslint leaflet-react/components/FleetMap.jsx
exit code 0
npm run build
✓ 2169 modules transformed.
✓ built in 797ms
```

The in-app browser displayed `/tracking` with the `Fleet positions` heading, vehicle list, data-source filter, Leaflet controls, and Streets/Satellite toolbar; the “The console encountered a rendering error” boundary was not present. This focused browser observation does not constitute the full route/theme smoke test. Browser console log inspection: NOT TESTED.

## Follow control and location follow-up

```text
npx eslint leaflet-react/components/FleetMap.jsx
exit code 0
npm run build
✓ 2169 modules transformed.
✓ built in 9.47s
```

In-browser interaction: enabled “Follow selected vehicle”, then selected a different bus. The checkbox remained enabled, the selected vehicle/map rendered, and browser console error log query returned `[]`.

```text
timeout 15s ./.venv-local/bin/python -m navic_tcp.client_main --registry config/devices.json --devices 3 --count 1 --interval 0.2 --port 5000 --base-lat 13.0405 --base-lon 77.6200
Receiver acknowledgements: 3 × status=accepted
```

After that command, a read of `/api/tracking/latest` still showed the legacy `SIM-*` rows at their old Chennai coordinates and old timestamps. `/health` reported `tcp: disabled`, so those acknowledgements came from a separate listener without the API persistence callback.

The browser API on port 8001 was traced to `/tmp/opencode/audit_live_copy.db` by inspecting the serving process's open database file. Three rows were appended to `location_history` using `simulated_telemetry()` with `simulated=1` and `data_source=simulator`; prior Chennai history was retained. A direct request to `/api/tracking/latest` returned all three latest points around HKBK, Bengaluru: `SIM-IMEI-000000000001` at 13.038216, 77.625557; `SIM-IMEI-000000000002` at 13.051186, 77.615953; `SIM-SERIAL-000003` at 13.041440, 77.612098. The in-app browser reloaded `/tracking` and showed all three with fresh timestamps (about 17 seconds old), with nine of nine fleet positions. The complete browser route/theme smoke suite remains NOT TESTED. The selected vehicle detail showed “Device-reported” even though the API marks its telemetry as simulator; this source-label mismatch needs follow-up.
