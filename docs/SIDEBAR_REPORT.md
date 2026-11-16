# Sidebar redesign report

## Changes

- Rebuilt the sidebar around a 272px expanded layout and an 80px rail using `--sidebar-w`; on mobile the sidebar overlays the page as a drawer.
- Added a glass brand tile, CBTMS label, sidebar command-palette trigger, section headings, animated active marker, hover/focus states, accessible links and badges, collapse shortcut, persisted preference, live status footer and mobile drawer behavior.
- Removed the duplicate topbar logo. The topbar still contains breadcrumbs, connection/data-mode pills, theme selector, command search and account menu.
- The sidebar and command palette now read routes from `navigation.js`. The dashboard and Devices badge share `selectDeviceAttention()`.
- Added `scripts/check_contrast.mjs` and `scripts/smoke_routes.mjs`; `npm run contrast` and `npm run smoke` scripts were added. Playwright is a development dependency only.
- During the required `npm run check`, existing lint errors were surfaced across the frontend. Changed derived state in dashboard selection/pagination, authentication boot handling, fleet user propagation, playback end state, and report switch scopes to remove those errors. The final check has no lint errors, with 36 warnings remaining.
- No files were archived; no route, backend, API, auth, or database changes were made.

## Evidence

Commands run from `frontend/`:

```text
npm run contrast
PASS light body text: 16.04:1 (required 4.5:1)
PASS light section label: 7.34:1 (required 4.5:1)
PASS light icon: 10.21:1 (required 3:1)
PASS light active icon/focus: 7.46:1 (required 3:1)
PASS light badge text: 6.57:1 (required 4.5:1)
PASS light control border: 4.38:1 (required 3:1)
PASS dark body text: 16.28:1 (required 4.5:1)
PASS dark section label: 10.77:1 (required 4.5:1)
PASS dark icon: 12.91:1 (required 3:1)
PASS dark active icon/focus: 9.54:1 (required 3:1)
PASS dark badge text: 6.57:1 (required 4.5:1)
PASS dark control border: 4.22:1 (required 3:1)

npm run check
ESLint: 0 errors, 36 warnings
Vite: 2,171 modules transformed; build completed

PLAYWRIGHT_BROWSERS_PATH=/tmp/cbtms-playwright npm run smoke
NOT TESTED: browser routes did not start because the Playwright Chromium executable was missing.
```

In-app browser observation: expanded and compact sidebar rendered on `/tracking`; clicking Collapse changed to the rail, reload retained the rail, Ctrl+B expanded it, and the sidebar search trigger opened the existing command palette. A light-theme screenshot at the in-app browser's 1100×900 viewport prompted a contrast adjustment; the subsequent screenshot showed readable inactive links.

## NOT TESTED

- The required all-routes × light/dark × 1440/1024/390 smoke loop. Chromium installation failed with `getaddrinfo EAI_AGAIN cdn.playwright.dev`.
- PNG screenshots at the requested 1440px layouts and 390px mobile drawer. The CUA browser screenshots were visible during the session but are not saved under `docs/screenshots/sidebar/`.
- Mobile drawer focus trap, overlay, Escape and route-change closure at 390px; keyboard tooltip appearance; no horizontal scroll at the requested widths; live map pan performance.

Run `cd frontend && npx playwright install chromium && npm run smoke` to produce the six screenshot files and route/viewport table. If credentials are required, provide `SMOKE_USER_ID` and `SMOKE_PASSWORD` in the shell environment; the smoke script does not store or print them. Manual checks are listed in [MANUAL_TESTS.md](/home/corben/Projects/NavIC/docs/MANUAL_TESTS.md).

Expected screenshot paths, all currently NOT PRESENT: `docs/screenshots/sidebar/expanded-light.png`, `collapsed-light.png`, `expanded-dark.png`, `collapsed-dark.png`, `tracking-sidebar.png`, and `mobile-drawer.png`.

## Decisions to review

- The logo asset has a dark banner background, so the asset remains unchanged inside a dark rounded square tile in both themes.
- Glass panes use 93% surface opacity and an 18px blur to preserve contrast over the ambient gradients. The Live tracking map itself receives no backdrop filter.
- Recently visited links and collapsible sections were skipped.

## Backups

Every pre-existing file changed for this task was copied with its relative path to [backups/sidebar_20261115T121058Z](/home/corben/Projects/NavIC/backups/sidebar_20261115T121058Z). This backup includes the additional frontend files touched while clearing lint errors.

## Files

- Added: `frontend/react-jsx/components/navigation/Sidebar.jsx`, `frontend/react-jsx/hooks/useSidebarState.js`, `frontend/react-jsx/utils/deviceAttention.js`, `frontend/scripts/check_contrast.mjs`, `frontend/scripts/smoke_routes.mjs`, `docs/SIDEBAR_DECISIONS.md`, `docs/SIDEBAR_REPORT.md`.
- Updated: `frontend/react-jsx/layouts/Shell.jsx`, `frontend/react-jsx/utils/navigation.js`, `frontend/react-jsx/components/navigation/CommandPalette.jsx`, `frontend/react-jsx/components/cards/FleetDashboard.jsx`, `frontend/css-styles/global/styles.css`, `frontend/package.json`, `frontend/package-lock.json`, and existing React files listed in the backup for lint repairs; `docs/MANUAL_TESTS.md`.
- Archived: none.
- Runtime dependencies: none. Development dependency: Playwright, for the requested browser smoke test.
