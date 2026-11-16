# CBTMS feature audit

Audit completed against the existing React/Vite, FastAPI, SQLAlchemy and TCP application. The continuation preserves the existing architecture. Automated evidence is listed below; local browser and live socket checks are limited by this execution environment.

| Feature | Status | Evidence / remaining limits |
|---|---|---|
| React/Vite shell, Dashboard, Tracking, Reports | Implemented; build and browser flow tested | `frontend/react-jsx/main.jsx`, `frontend/react-jsx/App.jsx`, `frontend/javascript-services/api.js`; `npm run build` passes. Browser sign-in, dashboard, role-based navigation, deep links and logout were exercised against the live dev server. |
| Dashboard counters and vehicle listing | Implemented and unit tested | `/api/dashboard/stats` calculates from buses, latest fixes, driver count and alert threshold. Idle/towed remain zero/unsupported unless reliable evidence exists. |
| Vehicle/driver/device CRUD | Implemented; backend logic tested | Management pages load API data with retry, empty and error states. Vehicle DTOs resolve real driver, route, device and status values; nullable route FK migration is additive. No browser form workflow test. |
| Trips | Read-only derived report implemented | `/trips` derives trips from recorded fixes; no persistent trip model or CRUD because the schema has no trip definition. |
| Alerts | Implemented and unit tested | Overspeed crossing, geofence transitions, stale-fix offline scan with cooldown, read/unread API. Tests cover overspeed/geofence and offline cooldown/read status. No notification delivery channel. |
| Geofences | Implemented | Validated circular regions with CRUD, active state and transition state persisted. Telemetry-triggered transition tested. No polygon support. |
| Settings | Implemented | Persistent overspeed threshold read/update; threshold is used by alert and report logic. |
| Reports | Implemented; selected calculations tested | Ten report categories use stored telemetry. Geodesic distance and measured stoppage periods tested; idle is explicitly unsupported without ignition data. Excel-compatible `.xls` export is HTML-based rather than a native `.xlsx` workbook. |
| Tracking latest fixes / historical playback | Implemented; backend and browser tested | Persisted location data, date-range history, marker state, playback controls and WebSocket client logic. Live Leaflet markers moved after simulator frames over the authenticated WebSocket; duplicate suppression and out-of-order persistence are covered by tests. |
| TCP protocol, validation, duplicates and registry | Implemented and unit tested | Verified existing newline-terminated JSON protocol in `navic_tcp/protocol.py`; tests cover framing, malformed packets, registry, duplicate and retry behavior. No physical IVTD connection. |
| FastAPI startup and route registration | Verified | `python backend/run.py` reached Uvicorn startup and clean timed shutdown; OpenAPI route inspection found dashboard, management, report, alert, geofence, settings, trip and WebSocket routes. A live HTTP request could not be made because local socket access is denied by the sandbox. |
| Authentication | Implemented and tested | Passwordless email magic links, hashed single-use tokens, DB-backed HttpOnly sessions, CSRF double-submit, logout/expiry/revocation, role guards and a safe user CLI. Legacy password/JWT login remains for API clients. Anonymous development access is opt-in only (`DEV_ALLOW_ANONYMOUS`). Browser magic-link login, viewer denial, refresh persistence and logout were exercised. |
| CORS, Vite proxy, API client | Configured and tested | Explicit development CORS origins; Vite proxies API/auth/WebSocket paths and bypasses HTML navigations that collide with SPA routes. The API client uses cookies and CSRF, stores no tokens in browser storage, and handles JSON, empty/non-JSON responses, HTTP errors and network failures. |
| PostgreSQL | Supported but not exercised | `DATABASE_URL` selects SQLAlchemy database; current environment has no PostgreSQL URL/client service configured. Current seed verification used the configured local development database. |
| Seed data | Implemented and idempotency verified | `python -m backend.python_sqlalchemy.database.seed` is additive and idempotent; it creates/updates six IVTD_BUS buses, six linked devices, six demo drivers, two routes and a geofence. Legacy `SIM-IMEI-*` devices/`VEH-SIM-*` vehicles from earlier demos are preserved rather than deleted; review or deactivate them manually for a six-bus-only demo. |
| GNSS metadata and generic NMEA decoder | Implemented and unit tested; receiver integration unverified | `navic_tcp/nmea.py`, `protocol.py`, `models.py`; optional metadata validation, persistence, device/history responses and WebSocket broadcast are tested. Generic GGA/RMC/GSA/GSV/GNS/VTG fixtures do not prove the IVTD emits those sentences. |
| NavIC/IVTD compatibility | Unverified | Exact receiver model, signals/bands, constellation support, configuration commands and raw output are absent. See `GNSS_COMPATIBILITY.md`. |
| Frontend automated interaction tests | Not configured | No frontend test runner is installed. Production build passes; interactive sign-in, role, deep-link, WebSocket and Leaflet checks were performed manually in the in-app browser. |

## Verified protocol and data flow

- TCP frames are UTF-8 JSON records terminated by newline, validated by `navic_tcp/protocol.py`; this is not evidence of raw NMEA over TCP.
- Registered device IDs are synchronized from SQLAlchemy device records into the TCP registry at startup and on management changes.
- Valid telemetry is persisted as `LocationHistory`, and accepted in-order updates are broadcast at `/ws/locations`; out-of-order history is retained without regressing latest position or triggering geofence transitions.
- Device list/dashboard/history APIs use persisted records. The UI marks telemetry from simulated devices/events explicitly.
- Six demo devices produced distinct Bengaluru-area paths; 120/120 frames were accepted, duplicates were rejected, and authenticated Leaflet markers moved from the WebSocket stream.
- Magic-link request/capture, single-use verification, cookie session, CSRF rejection/acceptance, logout, expired/reused links and viewer-role denial were verified against the live development database and browser.
