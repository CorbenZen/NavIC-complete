# Codex progress

Claims in earlier project reports are treated as unverified. Evidence below is limited to commands run during this session.

## Checklist

- [x] Phase 0: create snapshot, add project instructions, map initial structure, capture baseline.
- [ ] Phase 1: frontend, backend, migrations, and browser smoke test.
- [ ] Phase 2: roadmap audit and safe fixes.
- [ ] Phase 3: structure, formatting, VS Code setup, and environment example.
- [ ] Phase 4: explainability docs and comments.
- [ ] Phase 5: final checks, raw evidence, and report.

## Phase 0 evidence (2026-11-15)

- Snapshot: `backups/pre_codex_20261115_170000/project.tar`; command: `tar ... -cf backups/pre_codex_20261115_170000/project.tar .` (excluding dependencies, build output, backups, archive, and `.git`).
- Database backup: `pg_dump` unavailable. Project docs and Alembic configuration identify SQLite as local storage. No database dump attempted and no database data changed.
- Frontend root: `frontend/package.json`; Vite config: `frontend/vite/vite.config.js`; React source: `frontend/react-jsx/`; CSS: `frontend/css-styles/`; API/WebSocket clients: `frontend/javascript-services/`; Leaflet integration: `frontend/leaflet-react/`.
- Backend: `navic_tcp/` (API, models, store, TCP protocol/parser/server, simulator/client); FastAPI application packages and SQLAlchemy models/services/migrations are under `backend/`.
- Tests: `backend/tests/`, `tests/`, NMEA fixtures under `tests/fixtures/nmea/`. NMEA replay: `scripts/replay_nmea.py`. Configuration: `config/`.
- `python -m compileall -q backend navic_tcp tests`: PASS.
- `cd frontend && npm run check`: FAIL; lint reported 38 errors and 44 warnings, build did not run because lint failed.
- `./.venv-local/bin/ruff check .`: FAIL; 91 issues, including archived and backup files because command scope was broad.
- `./.venv-local/bin/pytest -q`: FAIL during collection; 17 import mismatches because pytest discovered duplicate modules under `backups/pre_audit_20261115_150308/`.
- `pg_dump` and globally available `ruff`/`pytest`: unavailable; project virtualenv provides Ruff and pytest.
- Migration baseline status: NOT TESTED yet; current migration files found are `0001` through `0007` under `backend/python_sqlalchemy/migrations/versions/`.
- Backend/frontend server startup and browser smoke test: NOT TESTED yet.

## Phase 1 investigation (2026-11-15)

- Follow-up fix for the reported `/tracking` “Illegal constructor” render failure: imported the `Map` and `Navigation` Lucide icons in `frontend/leaflet-react/components/FleetMap.jsx`. The JSX `<Map>` had no lexical import and collided with the browser global `Map` constructor; `Navigation` was also an unresolved JSX name in the toolbar.
- Focused validation after the fix: `npx eslint leaflet-react/components/FleetMap.jsx` PASS; `npm run build` PASS. The in-app browser displayed the tracking page with its vehicle list, filters, Leaflet map controls, and map-layer toolbar; the rendering-error boundary was absent. This was a focused visual check, not the full route/theme smoke test.
- Follow control repair: changed its map lookup to use `MapContainer`'s direct ref instance, matching installed React-Leaflet v5; the prior `leafletElement` wrapper was undefined and caused `map.flyTo` to throw. Focused ESLint and build pass. In-browser, enabling Follow and selecting another vehicle left the page rendered with the checkbox enabled and no console errors.
- HKBK location request: traced the browser API process on port 8001 to `/tmp/opencode/audit_live_copy.db`, appended three simulator-generated latest fixes there while preserving previous Chennai history, and confirmed `/api/tracking/latest` plus an in-app `/tracking` reload showed the three buses near HKBK with fresh timestamps. The API marked all three `simulated=true`, `data_source=simulator`. Follow-up: one selected vehicle detail still labeled its source “Device-reported”; investigate that UI source mapping. Full route/theme smoke suite remains NOT TESTED.

- `npm run build`: PASS; Vite transformed 2169 modules. Output warned that the main JS bundle is over 500 kB and noted upstream `use client` directives.
- `npm ls react react-dom react-leaflet --depth=0`: one installed copy each; React and React DOM are both `19.3.1`, React Leaflet is `5.0.0`.
- `npx eslint react-jsx --ext .jsx -f json`: 66 files, 38 errors and 44 warnings. Errors include 22 `react-hooks/set-state-in-effect`, two purity/ref issues, and 11 report-switch lexical declaration errors. The required build-gating lint cannot pass until these are corrected.
- `./.venv-local/bin/ruff check scripts/replay_nmea.py --fix`, followed by `./.venv-local/bin/ruff check scripts/replay_nmea.py`: PASS after removing unused imports and using builtin `TimeoutError`.
- `DATABASE_URL=sqlite:////tmp/navic_codex_migrations.sqlite3 ./.venv-local/bin/alembic -c backend/alembic.ini upgrade head`: PASS through `0007_roadmap_tables` on an isolated scratch DB.
- Scratch downgrade initially failed at revision 0006 because downgrade was unconditionally disabled. Its downgrade now restores NOT NULL only when no preserved NULL values exist. A second scratch downgrade then exposed a separate SQLite index ordering failure in `0004_user_id_password_auth`; full rollback remains FAIL/NOT TESTED after that point. No project DB was used by these migration commands.
- `APP_ENV=development DEMO_AUTH_BYPASS=true TCP_ENABLED=false ./.venv-local/bin/python backend/run.py` against the configured DB: FAIL, startup tried to backfill blank `location_history.data_source` and SQLite returned `attempt to write a readonly database`. No change to the DB was made.
- The same backend command against `/tmp/navic_codex_smoke.sqlite3`: startup PASS. Process was stopped after Vite could not be started for browser testing.
- `cd frontend && rm -rf node_modules/.vite && npm run dev -- --force --host 127.0.0.1 --port 5173 --strictPort`: Vite cache reset and dependency re-optimization began, but listen failed with `EPERM`. Retrying outside sandbox failed because port 5173 was already in use. Browser smoke test: NOT TESTED.
- `./.venv-local/bin/pytest -q backend/tests tests`: produced 13 passes then stalled without further output; stopped. `./.venv-local/bin/pytest -vv -x backend/tests tests`: the same live test directories collected 207 tests; the 14th test (`ApplicationCompositionTests.test_every_shared_route_is_registered`) stalled; stopped. Full test result NOT TESTED.
- Final scoped checks after editing the replay helper: `python -m compileall -q backend navic_tcp tests` PASS; `./.venv-local/bin/ruff check backend navic_tcp tests scripts` PASS; frontend lint remains at 38 errors and 44 warnings.
- Existing configured database access is read-only in this execution context. Do not alter permissions; migration-on-current-database and authenticated browser checks remain NOT TESTED.
