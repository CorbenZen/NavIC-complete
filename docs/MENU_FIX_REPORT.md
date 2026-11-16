# CBTMS menu and topbar fix report

## Bugs 1–4

1. **Collapsed rail square:** source inspection located the empty 28×28 `.sidebar-brand-row::after` pseudo-element and an obsolete collapse selector in the prior stylesheet. Those rules were removed from the active CSS and retained in the archive. The requested Playwright `elementFromPoint(55, 155)` output is NOT TESTED because Chromium could not launch; no browser `outerHTML` is claimed.
2. **Footer account menu:** the previous dropdown was an absolutely positioned child rendered under the filtered sidebar. The new shared `UserMenu` renders `ShellPopover` through a portal into `document.body`. The footer and topbar now share the same menu component and item handlers. Browser screenshot and interaction confirmation are NOT TESTED.
3. **Topbar chip clipped at the right edge:** `html` now reserves a stable scrollbar gutter; topbar controls stay in one flex row with 24px desktop padding; user metadata collapses below 1100px while the avatar and chevron remain. Geometry checks are in the smoke script but are NOT TESTED in a browser.
4. **Opaque topbar dropdown:** user and theme panels now share the strong glass surface, shared border/highlight/shadow, blur, fallback rules, and portal stacking. Contrast command output is recorded in [MENU_FIX_DECISIONS.md](MENU_FIX_DECISIONS.md). Visual blur screenshots are NOT TESTED.

## Files

- Created: `frontend/react-jsx/components/navigation/ShellPopover.jsx`, `docs/MENU_FIX_DECISIONS.md`, `docs/MENU_FIX_REPORT.md`, and `_archive/20261115T132602Z/frontend/css-styles/global/rail-artifacts.css`.
- Changed: `frontend/react-jsx/components/navigation/AccountMenu.jsx`, `frontend/react-jsx/components/navigation/ThemeSelector.jsx`, `frontend/react-jsx/components/navigation/Sidebar.jsx`, `frontend/react-jsx/components/navigation/index.js`, `frontend/react-jsx/layouts/Shell.jsx`, `frontend/css-styles/global/styles.css`, `frontend/scripts/check_contrast.mjs`, `frontend/scripts/smoke_routes.mjs`, `docs/MANUAL_TESTS.md`, and `docs/CLEANUP_LOG.md`.
- No source file was deleted or backend file changed. No dependency was added.

## Check results

- `cd frontend && npm run check`: exited 0. ESLint reported 0 errors and 36 warnings; Vite transformed 2172 modules and built. Existing warnings include the large bundle and two `use client` module directives.
- `cd frontend && npm run contrast`: all 30 light/dark checks printed PASS.
- `node --check scripts/smoke_routes.mjs` and `node --check scripts/check_contrast.mjs`: exited 0.
- `cd frontend && npm run smoke`: exited 1 before visiting routes. Chromium and Firefox Playwright executables were absent. Firefox is NOT TESTED. The test adds the requested diagnostic, layout, menu, stacking, route, and screenshot checks, but none ran in this environment.
- Screenshot files are NOT TESTED and were not generated. `docs/screenshots/menufix/` contains no screenshots. The target list in the smoke script is: collapsed rails light/dark; collapsed account menus light/dark; topbar account and theme menus light/dark; scrolled topbars; tracking menus open in Chromium and Firefox.
- Browser console/page errors are NOT TESTED because the smoke run did not reach app routes. Menu blur and Firefox blur are also NOT TESTED.

## Decisions and recovery

- Expanded footer menus open above the card; collapsed rail menus open 12px to the right of the rail; narrow screens use a viewport-clamped sheet.
- The prior CSS-only sidebar hints are archived at `_archive/20261115T132602Z/frontend/css-styles/global/rail-artifacts.css`; the reason is in `docs/CLEANUP_LOG.md`.
- Backups are under [backups/menufix_20261115T132602Z](/home/corben/Projects/NavIC/backups/menufix_20261115T132602Z), preserving each edited file's project-relative path. Restore those files to roll back. The archived rules are separate and are not loaded by the app.
- Run `cd frontend && npx playwright install chromium firefox` where the download host is reachable, then start the app and run `cd frontend && npm run smoke`. Manual browser steps are in [MANUAL_TESTS.md](MANUAL_TESTS.md).
