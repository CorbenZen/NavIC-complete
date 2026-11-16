# UI Fix 5 Report

## Changes

- Dashboard colors now share the deep teal accent and identical vehicle status hues in both themes. Status and badge foregrounds use shared theme tokens. `FleetDashboard` renders the ALL card in teal and uses the shared `StatusBadge`/`Badge` components.
- Dashboard “Needs attention” and “Fleet hygiene” now read a counts-and-targets-only summary from `GET /api/dashboard/admin-summary`, protected by `admin_user`. The frontend requests it only for `role === "admin"`; the panels are absent for other roles. The summary does not return fleet rows or record identifiers.
- Replaced remaining local neutral badge markup in Routes, Devices, Drivers, Vehicles, Trip replay, and the account menu with the shared `Badge`. Exempted badges from the `.kv-row` muted-label selector; that selector had overridden their tone colors and status contrast.

## Evidence

- `cd frontend && npm run check`: exit 0; ESLint reported 0 errors and 31 warnings; Vite build completed. The build also printed its existing large-chunk and `use client` directive warnings.
- `cd frontend && npm run contrast`: exit 0; all printed light/dark badge, vehicle status, primary button, avatar, and shell contrast checks passed (minimum reported text contrast was 5.40:1).
- `cd frontend && npm run smoke` with the disposable smoke session and scratch DB: **FAIL**, `12 routes × 2 themes × 2 browsers × 4 viewports`; 1,891 PASS lines and 17 FAIL lines. Failures included the collapsed sidebar popover bounds assertion, a Ctrl+K tooltip expectation, a strict-mode Dashboard-link locator, Firefox WebSocket/navigation console noise, and four light badge checks that reported Out Of N/w at 4.17:1. A separate browser style read after the `.kv-row` fix returned `rgb(55, 65, 81)` on the badge, while the contrast script reports 10.31:1 for that token; the smoke checker’s Out Of N/w result is therefore inconsistent with the computed style read and needs its own follow-up. The broad smoke flow exited before its role-test stage.
- Focused Playwright role flow against a disposable SQLite database passed in Chromium and Firefox: admin panels count 2 and summary status 200; newly registered student got HTTP 201, saw 0 panels, had no panel fetch on dashboard load, received HTTP 403 for a direct summary request, and had 0 page errors.
- `PYTHONPATH=. .venv-local/bin/pytest tests -q`: 44 passed, 3 subtests passed.
- `PYTHONPATH=. .venv-local/bin/pytest backend/tests/test_api_extended.py -q`: 14 passed.
- `DATABASE_URL=sqlite:////tmp/cbtms_uifix5_pytest.sqlite APP_ENV=development TCP_ENABLED=false PYTHONPATH=. .venv-local/bin/pytest backend/tests tests --ignore=backend/tests/test_backend_app.py -q`: 185 passed, 22 subtests passed.
- Full `pytest backend/tests tests` was attempted twice and did not complete: both runs stopped progressing at `backend/tests/test_backend_app.py::ApplicationCompositionTests::test_every_shared_route_is_registered`. Running the remainder separately above completed. A run without an isolated database also encountered a read-only SQLite error in `test_tcp_registry_contains_database_devices_after_sync` while `ensure_schema()` attempted its provenance backfill; no project database writes succeeded. The project SQLite file was not made writable.

## Other admin-looking access left unchanged

These were inspected but deliberately left unchanged for the owner’s decision:

- `/drivers` and its `/api/drivers` list are available to any authenticated user (`current_user`) and return driver email, phone, licence number, and assigned vehicles (`navic_tcp/fastapi_app.py`, `crud_routes` around line 3497).
- `/devices`, `/api/devices/{device_id}/telemetry/latest`, and `/api/devices/{device_id}/telemetry/observed-constellations` are available to authenticated users (`current_user`; around lines 3175–3203).
- `GET /settings` is available to authenticated users; `PUT /settings` requires `management_user` (around lines 2375–2388).
- Dashboard `/api/dashboard/summary` and `/api/dashboard/stats` remain available to authenticated users (around lines 1710 and 1777).
- Geofence reads and incident reads are available to authenticated users. Geofence create/update/delete and incident read mutations use `management_user` (CRUD registration around lines 3497 and incident routes around lines 3526–3586).
- The corresponding Drivers, Devices, Settings, and Geofences frontend routes remain reachable after sign-in; their access policy was not changed.

## Screenshots

Saved under `docs/screenshots/uifix5/`: Dashboard, Routes, Devices, GNSS diagnostics, Alerts, and Geofences in light and dark; Drivers light; expanded/collapsed sidebar at 996px; collapsed rail/footer and user menus in both themes; theme menus; and Chromium/Firefox topbar/menu screenshots at supported widths.

## NOT TESTED / follow-up

- **NOT TESTED:** the broad Playwright suite’s admin/student phase did not run because earlier shell checks aborted the browser runs. The focused two-browser role flow above covered the dashboard role behavior directly.
- **NOT TESTED:** completion of the unfiltered 212-item pytest suite; the backend app composition test stalled at the route-registration test in both runs. The other 185 tests completed when that file was excluded.
- The smoke-suite failures and the four inconsistent Out Of N/w reports need follow-up before the suite can exit successfully.

Backup: `backups/uifix5_20261115T175535Z/` (relative paths preserved). Browser and pytest databases were under `/tmp`; the configured project database was not made writable.
