# UI Fix 4 report

## Changes

1. **Light avatars and status chips:** added the shared `Avatar` component and used it for driver rows and account menu avatars. Light initials use accent ink on a pale teal fill; dark avatars use the dark surface and light initials. Success and info badges now use theme-aware soft fills. The contrast script reports avatar initials at **6.82:1 light** and **12.11:1 dark**; success and info badge text also pass at **6.20:1 or higher**.
2. **Geofences toolbar:** the map and toolbar now share a positioned, isolated map wrapper. On desktop the glass toolbar is inset 8px inside the map; on mobile it becomes a horizontally scrollable row above the Leaflet canvas. `isolation: isolate` keeps Leaflet's internal stacking context inside the map panel.
3. **Dashboard navigation:** the sidebar nav is reset to its start on initial mount. On route changes, it scrolls the active link with `block: nearest` only when that link is outside the visible nav. Screens below 1000px high use 40px navigation rows and tighter section spacing.
4. **Search fields:** shared wrapper styles now keep Geofences' magnifier inside the field. Replaced raw search/icon pairs in Fleet dashboard, GNSS diagnostics, and the command palette with `SearchInput`. A smoke assertion checks that search inputs use the shared wrapper.

## Evidence and test status

- `cd frontend && npm run check` — **PASS**. ESLint reported 0 errors and 35 pre-existing warnings; Vite built successfully, with existing chunk size and module-directive warnings.
- `cd frontend && npm run contrast` — **PASS**. Avatar initials and soft success/info badge contrast passed in light and dark themes; all existing glass, text, icon, menu, and topbar checks passed.
- `cd frontend && npm run smoke` — **NOT TESTED**. The command ran but Playwright could not find Chromium or Firefox. Installing to `/tmp/cbtms-playwright-browsers` failed because `cdn.playwright.dev` returned `getaddrinfo EAI_AGAIN`. The smoke script wrote no screenshots.
- `.venv-local/bin/pytest backend/tests tests` — **NOT TESTED**. Pytest collected 211 tests and stopped making progress in `test_backend_app.py`. A focused `timeout 90 .venv-local/bin/pytest -vv -s backend/tests/test_backend_app.py` timed out (exit 124) while `ApplicationCompositionTests::test_every_shared_route_is_registered` was running. A follow-up excluding that module completed with **183 passed, 1 failed, 22 subtests passed**; `FastApiReportTests::test_tcp_registry_contains_database_devices_after_sync` failed because SQLite returned `attempt to write a readonly database` while running `ensure_schema`. The database rejected the write; no backend files or database records were changed.
- Required screenshots `docs/screenshots/uifix4/{drivers-light.png,geofences-light.png,geofences-dark.png,sidebar-expanded-996.png,sidebar-collapsed-996.png}` — **NOT TESTED** because the browser executables were unavailable; these files were not produced.

## Files changed

- `frontend/react-jsx/components/common/Avatar.jsx` (new) and `components/common/index.js`
- `frontend/react-jsx/components/navigation/AccountMenu.jsx`
- `frontend/react-jsx/components/navigation/CommandPalette.jsx`
- `frontend/react-jsx/components/forms/SearchInput.jsx`
- `frontend/react-jsx/pages/users/Drivers.jsx`
- `frontend/react-jsx/components/cards/FleetDashboard.jsx`
- `frontend/react-jsx/pages/telemetry/Diagnostics.jsx`
- `frontend/react-jsx/pages/fleet/Geofences.jsx`
- `frontend/react-jsx/components/navigation/Sidebar.jsx`
- `frontend/css-styles/global/styles.css`
- `frontend/scripts/check_contrast.mjs`
- `frontend/scripts/smoke_routes.mjs`
- `docs/MANUAL_TESTS.md`

Backup: `/home/corben/Projects/NavIC/backups/uifix4_20261115T161555Z/`.
