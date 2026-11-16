# CBTMS UI fix 3 report

## Results by item

1. **Palette search overlap — changed.** The palette had its own magnifier and a keyboard glyph inside the shortcut badge. Removed the extra keyboard icon, aligned the one search icon 16px from the left, set 48px input padding, and moved the text hint to the right. `searchShortcutLabel()` now chooses `⌘K` on macOS and `Ctrl K` elsewhere; the sidebar and topbar search tooltip use the same label. The smoke script checks icon count, icon offset, input padding, clear text start, and the platform hint. Browser execution is NOT TESTED because both Playwright browser binaries are unavailable.
2. **Sidebar active bar — changed.** The previous absolute marker was positioned from measured offsets in the scroll nav. Removed the refs, measurement state, and update effect; the bar is now the active link's `::before`, selected by `aria-current="page"`. Smoke checks were added for hard loads and client navigation, expanded and collapsed. Browser execution is NOT TESTED.
3. **Collapsed footer — changed.** The rail footer now removes the card border/background and uses the existing account avatar as a 40px circular trigger. A 10px status badge reads the existing WebSocket state (green connected, amber reconnecting, red offline); the accessible name and portal tooltip include the state text. Geometry and screenshots are NOT TESTED in a browser.
4. **Multiplying theme controls — source trace and change.** `rg -n 'ThemeToggle|ThemeSelector' frontend/react-jsx` found one `ThemeSelector` render in `layouts/Shell.jsx` and no page-level `ThemeToggle` or page-actions registry. Removed the route-dependent `key` so the single topbar control does not remount on every route. The smoke script checks one theme control, search button, and user chip after hard loads and client navigation. Browser counts are NOT TESTED.
5. **Sign-in and sign-up glass — changed.** Added full-page ambient gradients, a centered glass card, glass feature tiles, a white rounded logo tile, theme-aware autofill selectors for WebKit and Firefox, and compact single-column mobile layout. The page can grow and scroll for the registration form. `npm run contrast` reports PASS for auth text and icons in both themes. Visual layout and actual browser autofill colors are NOT TESTED.
6. **Registration 405 — partly addressed; root cause NOT TESTED.** Source inspection shows the frontend calls `POST /api/auth/register`, Vite proxies `/api`, and FastAPI declares both `/api/auth/register` and `/auth/register` as POST. A guarded route-table walk printed 105 routes and both registration aliases with `('POST',)`. Existing registration tests cover student success, teacher without USN, duplicate User ID, duplicate USN, weak password, and password confirmation. The UI now maps HTTP 405 to a human-readable message. The requested Playwright request capture and direct/proxied curl reproduction could not run: Chromium is missing, Vite's local bind returned `listen EPERM`, and curl to the attempted backend port returned connection refused. No backend route or API contract was changed, and no claim is made that the reported 405 is resolved.
7. **Verification additions — implemented; browser checks NOT TESTED.** `scripts/smoke_routes.mjs` now includes the palette input geometry, active-bar geometry, route navigation singleton checks, auth layout checks, screenshots, and an opt-in `SMOKE_REGISTER_FLOW=1` register-then-login case. It records the registration request method, URL, and status. Use that opt-in only with a disposable test database.

## Command evidence

- `cd frontend && npm run check`: exit 0. ESLint reported 0 errors and 36 warnings; Vite transformed 2173 modules and built the bundle.
- `cd frontend && npm run contrast`: all 34 checks printed PASS, including auth glass text (16.95:1 light, 12.52:1 dark) and auth glass icons (7.10:1 light, 8.08:1 dark).
- `cd frontend && node --check scripts/smoke_routes.mjs && node --check scripts/check_contrast.mjs`: syntax checks completed with exit 0.
- `cd frontend && npm run smoke`: exit 1 before visiting routes. Output says Chromium's `chromium_headless_shell-1255` and Firefox's `firefox-1572` executables are missing. Route, interaction, visual, and screenshot checks are NOT TESTED.
- `DATABASE_URL=sqlite:////tmp/cbtms-uifix3-auth-tests.sqlite3 TCP_ENABLED=false APP_ENV=development .venv-local/bin/pytest backend/tests/test_registration.py -q`: 18 passed, 7 subtests passed in 1.73s.
- `.venv-local/bin/pytest backend/tests tests -q`: did not finish; it printed 13 passing markers and stalled when entering the modular backend application tests. A direct `TestClient` startup also failed to print its post-startup marker within a 12-second timeout. Full pytest status is NOT TESTED.
- Route check command using FastAPI's route objects and a visited-router set: `flattened routes: 105`; `('/api/auth/register', ('POST',), 'api_register')`; `('/auth/register', ('POST',), 'register')`.
- `curl` to the attempted local backend returned connection refused. Vite startup on port 15173 failed with `listen EPERM: operation not permitted`.

## Screenshots and NOT TESTED items

`docs/screenshots/uifix3/` was created, but it contains no screenshots because Playwright could not launch either browser. The smoke script's screenshot targets are collapsed footer light/dark, sign-in and sign-up light/dark, plus existing shell/tracking captures. Browser geometry, user interactions, actual autofill appearance, and the reported registration 405 remain NOT TESTED. Exact manual steps are in [MANUAL_TESTS.md](MANUAL_TESTS.md).

## Files changed

- Created: `frontend/react-jsx/utils/searchShortcut.js`, `docs/UI_FIX3_REPORT.md`.
- Changed: `frontend/react-jsx/components/navigation/CommandPalette.jsx`, `frontend/react-jsx/components/navigation/Sidebar.jsx`, `frontend/react-jsx/components/navigation/AccountMenu.jsx`, `frontend/react-jsx/layouts/Shell.jsx`, `frontend/javascript-services/api.js`, `frontend/css-styles/global/styles.css`, `frontend/scripts/smoke_routes.mjs`, `frontend/scripts/check_contrast.mjs`, `docs/MANUAL_TESTS.md`.
- No backend application, database, route, auth, or API contract code was changed. No dependency was added.
- Backup: [backups/uifix3_20261115T140500Z](/home/corben/Projects/NavIC/backups/uifix3_20261115T140500Z). It preserves the edited files at their original relative paths.
