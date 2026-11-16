# Manual test checklist

Run these after every deploy or major refactor.  Each step is a single
browser action; no automation is required.

## UI Fix 4 follow-up

Browser smoke and screenshots for this change are NOT TESTED: the installed
Playwright package has no browser executables, and download failed because
`cdn.playwright.dev` returned `getaddrinfo EAI_AGAIN`. Run `cd frontend &&
npx playwright install chromium firefox`, start the app, then run `cd frontend
&& npm run smoke` to capture the checks and screenshots below.

| # | Area | Exact steps | Expected |
|---|---|---|---|
| U4-1 | Avatar and badges | Open `/drivers` in light and dark mode; inspect driver initials, topbar avatar, sidebar avatar, and the user-menu header. Check Active and assigned-vehicle badges. | Light initials use a pale accent fill with readable dark initials; dark avatars retain a dark fill and light initials. Success/info badges use soft theme fills. `npm run contrast` prints PASS for both themes. |
| U4-2 | Geofences toolbar | Open `/geofences` at 1920×996, 1440×900, 1024×768 and 390×844. Compare the toolbar and map panel edges with the topbar; try Streets/Satellite, Draw, Reset view and Incidents. | Desktop toolbar stays inside the map at an 8px inset and clear of the topbar. On mobile it is a horizontally scrollable row above the map. Toolbar controls and incidents remain usable. |
| U4-3 | Dashboard in nav | At 1920×996 load `/`, then visit `/drivers` and `/settings`. Inspect `#primary-navigation .sidebar-nav.scrollTop` and the Dashboard link rectangle. | Dashboard is fully visible in the nav at each location; nav starts at `scrollTop === 0` unless the current active item must be brought into view. |
| U4-4 | Shared search fields | Visit Fleet dashboard, GNSS diagnostics and Geofences. Inspect each search field in DevTools. | One magnifier sits inside each field; each search input is inside `.search-input-wrapper`. |
| U4-5 | Requested screenshots | Save Drivers light, Geofences light/dark, and expanded/collapsed sidebar at 1920×996 under `docs/screenshots/uifix4/`. | All five PNGs are present and show the requested theme/layout state. |

## Menu and topbar repair

The cross-browser Playwright run is NOT TESTED in this environment: Playwright
could not download Chromium/Firefox because `cdn.playwright.dev` returned
`getaddrinfo EAI_AGAIN`. `/usr/bin/firefox` also exited with SIGSEGV when
launched by Playwright. Firefox NOT TESTED. When network access is available, run
`cd frontend && npx playwright install chromium firefox`, then start the backend
and frontend and run `cd frontend && npm run smoke`.

| # | Area | Exact steps | Expected |
| --- | --- | --- | --- |
| M1 | Stray rail square | At 1920×1040, open `/tracking`, press Ctrl+B to collapse, then inspect `document.elementFromPoint(55, 155)?.outerHTML` and computed styles in DevTools | No decorative empty square appears below the collapse handle; the old `.sidebar-brand-row::after` rule is absent |
| M2 | Collapsed account menu | Click the footer avatar in the 80px rail | Menu opens to the right of the rail, stays within the viewport, is outside `#primary-navigation`, and has no simultaneous sidebar tooltip |
| M3 | Account menu keyboard | Focus the footer avatar, press Enter, then ArrowDown and Escape | First item receives focus, ArrowDown moves to the next item, Escape closes and returns focus to the avatar |
| M4 | Account menu dismissal | Open the footer menu, click the map/page outside it | Menu closes |
| M5 | Expanded account menu | At 1440×900, expand the sidebar and click its footer user row | Menu opens above the footer card with Profile, Bus Pass, Feedback, CBTMS Support, Settings, Terms & Conditions, separator, Sign out |
| M6 | Topbar menus | Open the topbar account menu and the theme menu in turn on `/tracking` | Each popup is a direct child of `document.body`, has a translucent background and blur, and is painted above Leaflet |
| M7 | Theme choice | Open the theme menu and select Light, Dark, and System | Current theme is marked with a check; selection updates the existing theme preference |
| M8 | Width/scrollbar | Repeat at 1920×1040, 1440×900, 1024×768 and 390×844 | User chip and chevron remain visible, with its right edge at least 24px inside the content viewport; no horizontal scroll |
| M9 | Firefox | Repeat M1–M8 in Firefox | Same geometry and menu behavior; glass blur is visible behind a portal popup |

The Playwright diagnostic at the requested rail coordinate prints
`document.elementFromPoint(55, 155)?.outerHTML`, its computed styles, and up to
five ancestors. If browser installation remains unavailable, use the DevTools
steps above and save the same screenshots under `docs/screenshots/menufix/`.

## Shell redesign follow-up

| # | Area | Steps | Expected |
|---|------|-------|----------|
| S1 | Desktop expanded | At 1440×900, clear `cbtms-sidebar-collapsed`, open `/` | 272px glass sidebar, brand tile and labels, no topbar logo or horizontal scrolling |
| S2 | Desktop rail | Click Collapse or press Ctrl+B / Cmd+B; reload | 80px icon rail remains selected, labels appear on hover/focus, badges remain available |
| S3 | Breakpoint default | Clear `cbtms-sidebar-collapsed`; reload at 1024×768 then 1440×900 | Rail at 1024px, expanded sidebar at 1440px |
| S4 | Mobile drawer | At 390×844, open menu, tab through drawer, press Escape, reopen and click overlay | Drawer traps focus, locks body scroll, Escape/overlay/route change closes it, focus returns to menu button |
| S5 | Live badges | Compare Devices count to Dashboard “Needs attention”; compare Alerts count to unread count | Devices badge is offline plus stale telemetry; Alerts badge is unread alerts; zero values are hidden |
| S6 | Map performance | Open `/tracking`, drag and zoom the Leaflet map with sidebar open in both themes | Map pans without visible blur stutter; sidebar remains stationary |
| S7 | Screenshot capture | Run `npm run smoke` after installing Playwright Chromium | PNGs are written under `docs/screenshots/shell/` at the viewports listed in `docs/SHELL_REPORT.md` |

Browser checks not completed in the current environment: `cd frontend && npm run smoke` stopped before opening routes because Playwright could not find `chromium_headless_shell-1255/chrome-headless-shell-linux64/chrome-headless-shell`. Browser installation is NOT TESTED here. Install Chromium with `cd frontend && npx playwright install chromium`, then run `npm run smoke`; supply `SMOKE_USER_ID` and `SMOKE_PASSWORD` only if the app is not in its visible demo-auth mode. Shell screenshots are NOT TESTED and are not present yet. The script expects its configured browser to be available before it can save them.

| # | Area | Steps | Expected |
|---|------|-------|----------|
| 1 | **Backend health** | `curl /health` | `{"status":"ok","database":"ok","tcp":"listening"}` |
| 2 | **Alembic** | `alembic current` on fresh DB copy | head revision (`0007_roadmap_tables`) |
| 3 | **Public share — create** | POST `/api/buses/1/share` with auth | 200, returns `{token, id, ...}` |
| 4 | **Public share — open** | GET `/public/bus/<token>` in browser | JSON with `registration_number`, `route_name`, `source`, `source_badge`, `position` or `stale: true` |
| 5 | **Public share — headers** | `curl -I /public/bus/<token>` | `Cache-Control: no-store`, `X-Robots-Tag: noindex`, `Referrer-Policy: no-referrer` |
| 6 | **Public share — status** | GET `/public/api/bus/<token>/status` | Same shape as page, suitable for 30 s polling |
| 7 | **Public share — revoke** | DELETE `/api/buses/1/share/<id>` | 200, subsequent page/status → 410 |
| 8 | **Public share — expired** | Set `expires_at` in past, open page | 410 |
| 9 | **Public share — unknown** | Open `/public/bus/not-a-token` | 404 |
| 10 | **Data-source filter — dashboard** | Open `/`, change source dropdown | Table filters Hardware / Simulated / Test replay / All |
| 11 | **Data-source filter — live tracking** | Open `/tracking`, change source dropdown | List filters correctly |
| 12 | **Data-source filter — reports** | Open `/reports`, change source dropdown | Table + charts filter correctly |
| 13 | **Data-source filter — devices** | Open `/devices`, change source dropdown | Table filters correctly |
| 14 | **Data-source filter — URL sync** | Set filter, copy URL, open in new tab | Same filter applied; `?source=simulator` in URL |
| 15 | **Geofences page** | Open `/geofences` | List, map, draw mode, incidents panel all work |
| 16 | **Geofence create** | Click “Add geofence”, draw or enter values, Save | New circle appears on map and in list |
| 17 | **Geofence edit** | Click pencil on a row, change radius, Save | Circle updates |
| 18 | **Geofence delete** | Click trash, confirm | Row and circle removed |
| 19 | **Geofence incidents** | Click “Incidents (N)” badge | Panel opens, shows unread badge, “Mark all read” works |
| 20 | **Vehicles — share link copy** | Open `/vehicles`, click “Share” on a row, create token, click Copy | Toast “Link copied”, URL is `/public/bus/<plaintext>` |
| 21 | **Vehicles — revoke** | In share modal, click Revoke, confirm | Token disappears from list |
| 22 | **Alert incidents** | Trigger offline (stop simulator), wait >5 min | Incident appears in `/alerts`, grouped, not one per check |
| 23 | **Trip replay** | Open `/trips`, click Replay on a trip | Modal opens, plays back fixes with speed control |
| 24 | **Trip replay — simulated badge** | Replay a simulated trip | “Simulated trip data” badge shown |
| 25 | **Live map — trails** | Open `/tracking`, enable trails | Polylines show last N fixes per vehicle |
| 26 | **Live map — follow** | Select a vehicle, enable “Follow” | Map pans with vehicle |
| 27 | **Live map — route overlay** | Assign a route with stops, view map | Dashed line + stop markers visible |
| 28 | **Reports — charts** | Open `/reports`, run a trip report | Bar charts render for distance/vehicle/day |
| 29 | **Reports — print** | Click Print in report view | Print dialog opens with table + charts |
| 30 | **Settings — ETA toggle** | Open `/settings`, flip “Enable ETA calculations” | Saves, reads back `false` by default |
| 31 | **Theme — light/dark** | Toggle theme in header, reload | Preference persists, no flash |
| 32 | **Responsive — 1440px** | DevTools device toolbar 1440×900 | All pages usable, no horizontal scroll |
| 33 | **Responsive — 1024px** | DevTools device toolbar 1024×768 | Sidebar collapses, tables scroll |
| 34 | **Responsive — 390px** | DevTools device toolbar 390×844 (mobile) | Stack layout, touch targets ≥ 44 px |
| 35 | **PWA — install** | Lighthouse “Installable” audit | Passes (manifest, SW, HTTPS ready) |
| 36 | **PWA — offline shell** | DevTools Application → Service Workers → Offline, reload `/` | App shell loads, API calls fail gracefully |
| 37 | **Auth — magic link** | Enter email on `/sign-in`, check console capture | Link opens `/auth/verify?token=…`, sets HttpOnly cookies |
| 38 | **Auth — admin password** | POST `/auth/admin-login` with env `ADMIN_PASSWORD_HASH` | Returns session cookies + CSRF |
| 39 | **Auth — CSRF** | POST mutating endpoint without `x-csrf-token` | 403 |
| 40 | **Auth — cross-origin** | POST from different origin with cookies | 403 |
| 41 | **Rate limit — magic link** | Request >3 links in 10 min | 429 with `Retry-After` |
| 42 | **Rate limit — share page** | `curl` `/public/bus/<token>` >120×/min | 429 |
| 43 | **Audit log** | Perform create/update/delete, open `/settings` audit panel | Entries appear with actor, action, entity |
| 44 | **GNSS diagnostics** | Open `/diagnostics`, select a device | Observed constellations excludes simulator |
| 45 | **Trip replay interpolation** | Replay a trip with gaps | Marker moves smoothly between fixes (visual) |
| 46 | **NMEA replay script** | `python scripts/replay_nmea.py tests/fixtures/nmea/demo.nmea --simulated` | Sends telemetry, server accepts, no checksum errors |
| 47 | **Simulator Bengaluru** | Start simulator with default registry | Devices follow elliptical paths around 13.0435, 77.62 |

---

### Quick smoke script (run in repo root)

```bash
# Backend
cd /home/corben/Projects/NavIC
.venv-local/bin/python -m pytest backend/tests/ tests/ -q
.venv-local/bin/python -m ruff check navic_tcp backend tests

# Frontend
cd frontend && npm run build
```

### UI fix 3 follow-up checks

The automated browser portion is NOT TESTED in this environment because the
Playwright Chromium and Firefox binaries are unavailable. The attempted Vite
bind was rejected with `listen EPERM`, so the registration request could not be
captured through a running proxy here. Run the following from a normal local
terminal with the backend and frontend available; use a disposable SQLite DB
for the registration flow so the new smoke account does not enter project data.

1. Start the backend against a temporary DB: `DATABASE_URL=sqlite:////tmp/cbtms-uifix3.sqlite3 TCP_ENABLED=false .venv-local/bin/python backend/run.py`.
2. Start Vite in another terminal with `BACKEND_URL=http://localhost:8000 npm run dev -- --host 127.0.0.1`.
3. From `frontend/`, run `npm run smoke`. To run the register-then-login browser case, use a separate fresh temporary database and set `SMOKE_REGISTER_FLOW=1` for the smoke command. This creates one throwaway account in that database.
4. To inspect the reported 405 request, open DevTools Network, submit the registration form, and record the request method, full URL, response status and JSON. Repeat the same JSON with `curl -i -X POST http://localhost:8000/api/auth/register -H 'Content-Type: application/json' -H 'Accept: application/json' --data '<same JSON>'`, then through Vite at `http://localhost:5173/api/auth/register`.
5. In Chromium and Firefox, open `/sign-in` and `/sign-up` in both themes at 1920×1040 and 390×844. Confirm the glass card, long-form scrolling, autofilled input colors, and save screenshots under `docs/screenshots/uifix3/`.


## Account and backend-link manual checks

1. Copy `.env.example` to `.env`, set `DEMO_AUTH_BYPASS=false`, and set `BACKEND_URL` to the FastAPI address (default `http://localhost:8000`). Run `.venv-local/bin/alembic -c backend/alembic.ini upgrade head`, then `./start-navic.sh`.
2. In Firefox, open `http://localhost:5173/sign-up`, register a teacher without a USN, and confirm the app opens `/sign-in` with the User ID filled and no password in the address bar. Reload, sign in, close Firefox, reopen it, and confirm the session remains signed in. Sign out and confirm `/api/auth/me` returns 401 after cookie removal. Repeat for a student with a USN.
3. Try the same User ID with different capitalization and a duplicate student USN; each should show a 409 message. Try a weak password and mismatched confirmation; each should be rejected before submission.
4. Open `/trips`, stop the backend, and confirm one shell banner says “Backend unreachable, retrying...”, the status pill says “API offline”, and existing trip data remains visible but dimmed. Restart the backend, use Retry, and confirm the page recovers without a reload. Repeat at both `http://localhost:5173` and `http://127.0.0.1:5173`.
5. To inspect the saved user row, run the parameterized `psql` query in `docs/AUTH_FIX_REPORT.md`; it intentionally prints only a truncated password hash.
