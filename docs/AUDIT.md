# CBTMS NavIC — Audit (current)

Date: 2026-11-15. Full detail, evidence and command output: `docs/AUDIT_FINDINGS_2026-11-15.md`.
Progress tracker: `docs/AUDIT_PROGRESS.md`. Decisions: `docs/AUDIT_DECISIONS.md`.

## Baseline

- Backend + TCP tests: **170 passed, 28 subtests**.
- Frontend build: **passes** (pre-existing chunk-size and lucide `"use client"` warnings).
- Python syntax compile: **passes**.
- Ruff: **66 errors** (unused imports, undefined names, duplicate handlers).
- Alembic: DB is at revision `0004`, head is `0006`; upgrade tested on a DB copy and succeeds.
- Backend boots and `/health` reports `database: ok`, `tcp: listening`.
- Backups: `backups/pre_audit_20261115_150308/` and `.sqlite` copy. No `pg_dump` (SQLite only).

## Confirmed bugs (being fixed)

1. `ShareToken` never imported in `navic_tcp/fastapi_app.py` → every share endpoint returns 500.
2. `Geofences.jsx` references undefined `markAllIncidentsRead` → page crashes with unread incidents.
3. `Vehicles.jsx` "Copy" share link builds `/public/bus/<numeric id>` (invalid).
4. Duplicate `mark_incident_read` / `mark_all_incidents_read` definitions; 66 ruff errors.
5. Geofence incident list resolves devices with `db.get(TrackingDevice, str_pk)` → always `None`.

---

# NavIC CBTMS — Codebase Audit (historical, 2026-11-06)

Date: 2026-11-06
Scope: repository at `/home/Corben/Desktop/NavIC` (no usable Git history; `.git` is empty).

## A. Current architecture

- **Frontend:** React 19 + Vite 8, React-Leaflet 5 / Leaflet 1.9, lucide-react icons. The React entry is `frontend/react-jsx/main.jsx` (bootstrap, layouts, pages, components) with styles in `frontend/css-styles/global/styles.css`.
- **Backend:** FastAPI + Uvicorn (`navic_tcp/fastapi_app.py`), SQLAlchemy 2 ORM, asyncio TCP telemetry listener (`navic_tcp/server.py`), in-memory telemetry store (`navic_tcp/store.py`), registry (`navic_tcp/registry.py`), NDJSON protocol (`navic_tcp/protocol.py`), NMEA adapter (`navic_tcp/nmea.py`).
- **Database:** PostgreSQL via `DATABASE_URL`; local default is SQLite (`navic_dev.db`). Tables are created with `Base.metadata.create_all` plus ad-hoc additive `ALTER TABLE` migrations. No Alembic.
- **Realtime:** in-process WebSocket hub at `/ws/locations`; TCP callback persists and publishes.
- **Legacy artifacts:** None. Historical AngularJS bundles were archived and removed.

## B. Frontend pages

Existing (single-file implementation):
- Dashboard (fleet pills, device table).
- Tracking (Leaflet map, vehicle sidebar, history playback).
- Reports (10 report types, CSV/XLS/print).
- Vehicles, Drivers, Routes, Devices, Geofences (generic CRUD table + modal).
- Trips (derived read-only report).
- Alerts (read/unread), Settings (overspeed threshold).
- Login prompt appears only after a 401.

Deficiencies:
- Monolithic, heavily compressed code; no component structure or tests.
- Generic CRUD table is not a fleet-management UX; no detail views, assignment workflows, validation guidance, route geometry editor, or device diagnostics panel from the shell.
- Dashboard has no charts, map preview, device connectivity panel, or operational alerts summary.
- No first-class GNSS diagnostics route, no breadcrumbs, no mobile sidebar.
- Relies on `sessionStorage` token only in non-development builds; no auth context or logout.
- No frontend test runner.

## C. Backend modules

- `fastapi_app.py` — app, auth, dashboard stats, reports, CRUD, alerts, geofences, settings, WebSocket, lifespan.
- `server.py` — NDJSON framing, validation, registry enforcement, UUID dedupe, ACK/error, in-memory sessions.
- `store.py` — latest state + bounded history (process memory).
- `protocol.py` — strict version-1 telemetry schema, optional GNSS metadata.
- `registry.py` — file-based device registry plus runtime upsert/remove.
- `nmea.py` — generic NMEA decoder, not wired to TCP.
- `client.py` — simulator + retrying client.
- `api.py`, `server_main.py` — legacy standalone read-only HTTP demo.

Deficiencies:
- `fastapi_app.py` is dense and hard to audit; no service/reporting separation.
- No password hashing beyond unsalted SHA-256; no login rate limiting; WebSocket unauthenticated in production.
- Device TCP identity is possession of a registered ID only; no optional shared-secret check.
- No audit log.
- Dashboard statistics are minimal; no summary endpoint (charts, connectivity, recent alerts).
- Reports lack daily activity, vehicle activity/utilization, route activity and device connectivity; `idle` is reported unsupported because ignition is not persisted even though the protocol carries it.
- No API endpoint for all latest tracking positions or latest device telemetry.
- No request-level validation of route geometry; routes only have text start/destination.
- `health` does not check the database.
- No CSV export endpoint (client-side only).

## D. Database schema

Existing models: `buses`, `tracking_devices`, `location_history`, `users`, `drivers`, `routes`, `geofences`, `alerts`, `device_geofence_state`, `system_settings`.

Relationships are mostly sound: bus → driver/route (SET NULL), device → bus (SET NULL), location/alert → device by `device_id`. Unique keys on vehicle/registration/device/license/email/route name/identifier. Index on `(device_id, timestamp)`.

Gaps:
- `location_history` drops protocol `ignition` and `odometer`, so idle and odometer reporting are impossible.
- Routes have no stops/geometry/colour.
- Drivers cannot be deactivated.
- No audit table.
- Ad-hoc migrations only; no versioned migration path.
- SQLite foreign keys are not enabled by default.

## E. REST APIs (current)

`/health`, `/api/dashboard/stats`, `/api/reports/{type}`, `/settings`, `/alerts`, `/trips`, `/auth/login`, `/auth/me`, `/buses` CRUD, `/buses/{id}/history`, `/devices` CRUD/list, `/drivers` CRUD, `/routes` CRUD, `/geofences` CRUD, `/ws/locations`.

Aliases suggested by the spec (`/api/vehicles`, `/api/tracking/latest`, `/api/devices/{id}/telemetry/latest`, `/api/reports/trips|stoppages|vehicle-activity`) are absent.

## F. TCP protocol and receiver

- **Protocol:** newline-delimited UTF-8 JSON, version 1. Strict required fields: `protocol_version`, `type`, `message_id` (canonical UUID), `device_id`, `timestamp` (RFC 3339 UTC `Z`), `latitude`, `longitude`, `speed`, `course`, `ignition`, `simulated`; optional `odometer`, `gnss`.
- **Framing:** `readuntil(b"\n")`, CRLF accepted, 64 KiB max, oversized/unterminated frames get an error then close.
- **Identity:** `device_id` must exist in the registry (file entries + DB devices synced at startup/CRUD).
- **Dedupe:** `(device_id, message_id)` LRU (10k default) in memory; DB unique `message_id` is the durable guard.
- **ACK:** `{"type":"ack","message_id":...,"status":"accepted|duplicate","duplicate":bool,"received_at":...}`.
- **Errors:** `{"type":"error","message_id":...,"error":{"code","message"}}`.
- **No hardware test.** The exact IVTD firmware contract is unverified; NDJSON is preserved.

## G. WebSocket

`/ws/locations` accepts clients, broadcasts accepted in-order telemetry. No auth, no snapshot, no heartbeat, no per-client backpressure.

## H. Leaflet

Markers from persisted latest fixes, status-coloured div icons, OSM/Esri satellite layers, history polyline and fit-all. No clustering, no stale/unknown-position explanation, no route stop display.

## I. Authentication and security

- Dev mode (`APP_ENV=development`) bypasses auth with a synthetic admin.
- Production requires `JWT_SECRET`; JWT HS256 hand-rolled; management role check for `admin`/`transport`.
- Passwords: unsalted SHA-256 (weak).
- No login rate limiting, no WebSocket auth, no TCP shared secret, public dashboard/report endpoints, no audit logging.
- CORS is explicit; API base and secrets are not placed in the frontend.

## J. Tests and build status (measured)

- Backend: `python -m unittest discover -s backend/tests -t .` → **93 tests pass** after installing `backend/requirements.txt` (venv initially had no packages).
- TCP suite: `python -m unittest discover -s tests` → **44 tests pass**.
- Frontend: `cd frontend && npm run build` → **passes** (Vite/Rolldown warning about lucide `"use client"` only).
- No browser/Frontend tests. No live hardware. PostgreSQL not exercised.
- `tests/__pycache__` references a deleted `test_http_management.py`; not part of the current suite.

## K. Missing features and bugs

1. Persist ignition/odometer and implement real idle periods.
2. Route stops/geometry and assignment visibility.
3. Driver deactivation and safe delete.
4. Dashboard summary + charts + connectivity + alerts.
5. Live tracking first-class page with robust stale/no-fix handling and authenticated WS.
6. GNSS diagnostics page reading real persisted fields only.
7. API aliases, latest telemetry endpoints, CSV export.
8. Login rate limit, stronger password hashing, audit log, WS auth, optional device token.
9. Health check includes DB; configurable offline threshold.
10. Versioned migrations, Docker/compose, `.env.example`, deployment docs.
11. Frontend componentisation, responsive shell, loading/error/empty states, tests.

## L. External services and credentials

Required now: none. PostgreSQL for production, map tiles (OpenStreetMap-compatible), optional SMTP/SMS and reverse-geocoding/OSRM later. No paid API is introduced. `JWT_SECRET` and optional `DEVICE_AUTH_TOKEN` must be operator-supplied.

## M. Implementation roadmap

1. Backend foundation: schema helper, security module, reporting module, model additions (ignition, odometer, route stops, driver active, audit log), protocol optional `auth_token`, TCP secret + idle timeout.
2. Backend API: dashboard summary, latest tracking/telemetry, report types/aliases, vehicle/driver/route/device improvements, settings, alerts read-all, health, CSV, WS auth, audit.
3. Frontend redesign: design system, shell, dashboard, live tracking, management pages, trips, reports, diagnostics, alerts, settings, auth.
4. Tests: extend backend suite (dashboard, reports, auth, protocol auth, routes/stops, latest endpoints), frontend build + browser verification with simulator.
5. Deployment: env template, Dockerfiles, compose, nginx, migrations, README.
6. Verification: full data flow TCP → DB → WS → UI; document hardware limits.

## N. Risks and unresolved hardware questions

- Exact GNSS receiver model, constellations (including NavIC), NMEA output, Quectel module, SIM/APN and firmware framing are unverified.
- Real device authentication/TLS is not specified; a shared token is optional and documented, not claimed as firmware support.
- Public map tile usage must respect provider policy; the app uses standard attribution and allows tile URL overrides.
- No production PostgreSQL instance or browser automation was previously available; both must be re-verified here.
