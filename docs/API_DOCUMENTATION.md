# API Documentation

The website API is served by the modular FastAPI application at
`backend.python_fastapi.application.main:app`. It exposes 86 registered route entries: 84 HTTP path
operations (including the SPA fallback), one WebSocket route and one static
`/assets` mount.

- Swagger UI: <http://localhost:8000/docs>
- OpenAPI JSON: <http://localhost:8000/openapi.json>
- ReDoc: <http://localhost:8000/redoc>

## 1. Conventions

### Authentication

Most endpoints use the `current_user` dependency, which accepts either:

- `Authorization: Bearer <token>` — HMAC-signed token from
  `issue_access_token()` / the login endpoints; or
- the opaque `navic_session` cookie set by magic-link verification or logout
  sessions.

In development, `DEMO_AUTH_BYPASS=true` returns a demo administrator and makes
protected endpoints callable without credentials. It is disabled by default and
only honoured when `APP_ENV` is development/dev/local.

Requests without valid credentials return:

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer
Content-Type: application/json

{"detail": "valid bearer token required"}
```

State-changing requests authenticated by cookie must also send `X-CSRF-Token`
matching the `navic_csrf` cookie.

Endpoints marked **public** below need no credentials.

### Validation errors

Pydantic validation failures return `422 Unprocessable Entity`:

```json
{
  "detail": [
    { "type": "missing", "loc": ["body", "username"], "msg": "Field required", "input": {} }
  ]
}
```

### Elevation

`/api/admin/*` endpoints are for administrator workflows. The route dependency
resolves the current user; role checks are part of the handler logic in
`navic_tcp/fastapi_app.py`. The development demo user has the `admin` role.

## 2. System

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/health` | public | Status, database reachability, TCP state, environment, version, WebSocket client count |
| GET | `/api/meta` | public | Version, environment, auth methods, report names, GNSS capability, simulation notice |
| GET | `/docs`, `/redoc`, `/openapi.json` | public | API documentation |

`GET /health` example:

```json
{
  "status": "ok",
  "database": "ok",
  "tcp": "listening",
  "environment": "development",
  "version": "3.0.0",
  "websocket_clients": 0
}
```

`tcp` is `listening`, `disabled` or `error`, depending on the embedded receiver.

## 3. Authentication

| Method | Path | Request body | Response |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | `first_name`, `last_name`, `account_type`, `user_id`, `password`, `confirm_password`, student `usn_id` | `201` account created; no email/verification step |
| POST | `/api/auth/login` | `{"user_id": "...", "password": "..."}` | `200` token + user + session cookies |
| POST | `/api/auth/logout` | – | revokes session and clears cookies |
| GET | `/api/auth/me` | – | current authenticated user |
| POST | `/api/auth/verify-email` | `{"token": "..."}` | legacy: consumes verification link and starts session |
| POST | `/api/auth/resend-verification` | `{"email": "..."}` | legacy, generic `202`; rate limited |
| GET | `/api/auth/verification-status` | – | legacy: current user's verification status |
| POST | `/auth/register` | same as `/api/auth/register` | `201` (SPA alias) |
| POST | `/auth/login/id` | same as `/api/auth/login` | `200` (SPA alias) |
| POST | `/auth/login` | `{"email": "...", "password": "..."}` | legacy email-password login for API clients |
| POST | `/auth/verify-email` | `{"token": "..."}` | consumes the one-time verification link, marks email verified and creates session |
| POST | `/auth/resend-verification` | `{"email": "..."}` | generic `202`; rate limited and subject to resend cooldown |
| GET | `/auth/verification-status` | – | current authenticated user's verification status |
| POST | `/auth/admin-login` | `{"email": "...", "password": "..."}` | token + user, admin role required |
| POST | `/auth/magic-link` | `{"email": "..."}` | `202 {"message": "...", ...}` |
| POST | `/auth/magic-link/verify` | `{"token": "..."}` | sets session + CSRF cookies, returns user |
| GET | `/auth/google/login` | – | `302` redirect to Google |
| GET | `/auth/google/callback` | – | `302` redirect to the frontend; sets session cookies |
| POST | `/auth/logout` | – | revokes the session, clears cookies |
| GET | `/auth/me` | bearer or cookie | current user |

User ID/password behaviour:

- Registration requires first and second names, `account_type`, a unique
  `user_id`, and matching passwords of 8–128 characters with at least one
  letter. Students must supply `usn_id`; teachers must not.
- User IDs are normalised to upper case and limited to 3–32 characters. A
  duplicate returns `409 {"detail": "This ID is already registered. Please choose another ID."}`.
  A duplicate student USN returns `409 {"detail": "This student USN is already registered."}`.
- `POST /api/auth/login` accepts a User ID or the configured administrator
  email. Unknown IDs return `404 {"detail": "No account found with this ID."}`;
  a wrong password returns `401 {"detail": "Incorrect password. Please try again."}`.
- Empty credentials are rejected by validation; the sign-in form shows
  `Please enter your ID and password.` before submitting.
- Successful login returns a bearer token plus `navic_session` (HttpOnly) and
  `navic_csrf` cookies. Repeated failures are rate limited with `429`.
- The administrator is still verified against `ADMIN_EMAIL`/`ADMIN_PASSWORD_HASH`
  and is promoted to the `admin` role only after that check.

Legacy password/verification behaviour:

- `POST /auth/login` keeps the email-password contract for API clients.
- Correct credentials for an unverified legacy account return `202` and trigger
  a verification email; they do not create an authenticated session.
- Verification links expire, are stored as hashes, and work once. Invalid,
  expired or previously consumed links return `400`.
- The email-registration form is intentionally replaced by the User ID flow;
  existing email accounts keep their rows and can use the retained verification
  and magic-link endpoints. Normalized email and student USN still have unique
  database indexes.
- Magic-link request returns `202` for known and unknown addresses alike (no
  account enumeration). In development the captured mail is written to
  `EMAIL_CAPTURE_FILE` (`dev-mail.jsonl` by default).

## 4. Users and student services

| Method | Path | Body | Description |
| --- | --- | --- | --- |
| GET | `/api/user/me` | – | Current profile (email, name, role, department, USN, completeness) |
| PUT | `/api/user/profile` | `{"full_name", "phone", "department", "usn"?}` | Update the signed-in profile |
| GET | `/api/users/me/preferences` | – | Notification/map/theme preferences |
| PUT | `/api/users/me/preferences` | `PreferencesIn` | Save preferences |
| POST | `/api/feedback` | `{"rating": 1-5, "category": enum, "comments": "..."}` | `201`; feedback row |
| POST | `/api/support` | `{"subject", "category", "description", "priority", "contact"?}` | `201`; support ticket |
| GET | `/api/support/info` | – | **public** support contact details |
| GET | `/api/user/terms` | – | **public** terms and privacy sections |
| GET | `/api/user/bus-pass` | – | The signed-in student's active pass |
| POST | `/api/admin/bus-passes` | `{"email", "bus_id", "expires_at"}` | `201`; issue a QR pass |
| GET | `/api/bus-pass/verify/{token}` | – | **public** pass verification |

`FeedbackIn.category` is one of `Bus Service`, `Driver Behaviour`, `Route`,
`Tracking Accuracy`, `Application Issue`, `Other`.
`SupportIn.category` is one of `Account`, `Bus Pass`, `Tracking`, `Safety`,
`Application`, `Other`; `priority` is `LOW`, `NORMAL` or `HIGH`.

## 5. Fleet

Vehicles are exposed under both `/buses` and `/api/vehicles`; drivers, routes
and geofences have `/api/...` aliases. All are authenticated.

### Vehicles

| Method | Path | Body | Description |
| --- | --- | --- | --- |
| GET | `/buses` | – | List vehicles with driver, route, device and latest status |
| POST | `/buses` | `BusIn` | Create a vehicle |
| GET | `/buses/{bus_id}` | – | One vehicle |
| PUT | `/buses/{bus_id}` | `BusIn` | Update a vehicle |
| DELETE | `/buses/{bus_id}` | – | Delete a vehicle |

`BusIn`:

```json
{
  "vehicle_id": "BUS-01",
  "registration_number": "KA01AB1234",
  "driver_name": "A. Driver",
  "route_name": "North",
  "driver_id": 1,
  "route_id": 2
}
```

`GET /buses` item shape (abridged):

```json
{
  "id": 1,
  "vehicle_id": "IVTD_BUS_01",
  "registration_number": "KA-04-HB-1001",
  "driver_id": 1,
  "driver_name": "Demo Driver 01",
  "route_id": 2,
  "route_name": "Demo North Route",
  "device_id": "IVTD_BUS_01",
  "status": "On Move",
  "status_key": "on_move",
  "last_seen": "2026-11-06T03:30:28.188000+00:00",
  "speed": 12.98,
  "latitude": 13.037235,
  "longitude": 77.622036,
  "ignition": true,
  "simulated": true
}
```

Status keys: `on_move`, `stopped`, `idle`, `out_of_network`, `toing`.

### Drivers, routes and geofences

| Resource | Endpoints |
| --- | --- |
| Drivers | `GET/POST /drivers`, `PUT/DELETE /drivers/{item_id}` (+ `/api/drivers` aliases) |
| Routes | `GET/POST /routes`, `PUT/DELETE /routes/{item_id}` (+ `/api/routes` aliases) |
| Geofences | `GET/POST /geofences`, `PUT/DELETE /geofences/{item_id}` (+ `/api/geofences` aliases) |

- `DriverIn`: `name`, `email`, `license_number`, `phone?`, `active`.
- `RouteIn`: `name`, `identifier`, `start_point?`, `destination?`, `color`,
  `stops` (max 200 `RouteStop` items).
- `RouteStop`: `name`, `latitude`, `longitude`.
- `GeofenceIn`: `name`, `latitude`, `longitude`, `radius_m` (0–100000),
  `active`.

### Devices

| Method | Path | Body | Description |
| --- | --- | --- | --- |
| GET | `/devices` | – | `{"devices": [...]}` with identity, latest fix, connection state and GNSS compatibility |
| POST | `/devices` | `DeviceIn` | Create a tracking device |
| PUT | `/devices/{device_pk}` | `DeviceIn` | Update a device |
| DELETE | `/devices/{device_pk}` | – | Delete a device |

`DeviceIn`: `device_id`, `device_type` (default `unknown`),
`identifier_type` (default `serial`), `bus_id?`, `simulated`, `active`.

### Settings, trips, dashboard, reports and audit

| Method | Path | Description |
| --- | --- | --- |
| GET | `/settings` | `{"overspeed_kmh": 81.0, "device_offline_minutes": 5.0}` |
| PUT | `/settings` | `{"overspeed_kmh": 1-300, "device_offline_minutes"?: 1-1440}` |
| GET | `/trips` | Trip groups derived from stored telemetry |
| GET | `/api/dashboard/summary` | Fleet, device, driver, route and alert summary |
| GET | `/api/dashboard/stats` | Per-status fleet counters |
| GET | `/api/reports/{report_type}` | Report data; `report_type` from `/api/meta` (`daily`, `km`, `stoppage`, `trip`, `utilization`, …) |
| GET | `/api/reports.csv` | CSV export of the same report data |
| GET | `/api/audit` | Recent management audit entries |

Report query parameters include `start_date`, `end_date`, `limit`, `offset`.
Unsupported report names return `404`; a reversed date range returns a client
error.

## 6. Telemetry

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/tracking/latest` | Latest fix and derived status for every device (`{"generated_at", "offline_after_seconds", "vehicles": [...]}`) |
| GET | `/buses/{bus_id}/history` | Recent fixes for a vehicle's device |
| GET | `/api/devices/{device_id}/telemetry/latest` | Latest stored fix for one device |

Tracking item (abridged):

```json
{
  "device_id": "IVTD_BUS_01",
  "bus_id": 1,
  "vehicle_id": "IVTD_BUS_01",
  "registration_number": "KA-04-HB-1001",
  "driver_name": "Demo Driver 01",
  "route_name": "Demo North Route",
  "status": "On Move",
  "status_key": "on_move",
  "status_reason": "fresh_moving",
  "tcp_online": true,
  "latitude": 13.037235,
  "longitude": 77.622036,
  "speed": 12.98,
  "ignition": true,
  "course": 265.27,
  "timestamp": "2026-11-06T03:30:28.188000+00:00"
}
```

### Telemetry ingestion

Live frames are accepted by the independent TCP receiver
(`navic_tcp.server.TelemetryServer`, default `127.0.0.1:5000`) using the
newline-delimited JSON protocol in `navic_tcp/protocol.py`. There is no HTTP
ingest endpoint; the backend's `TCPTelemetryBridge` sends frames over that same
TCP socket.

Frame:

```json
{
  "protocol_version": 1,
  "type": "telemetry",
  "message_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "device_id": "IVTD_BUS_01",
  "timestamp": "2026-11-06T03:30:28.188Z",
  "latitude": 13.037235,
  "longitude": 77.622036,
  "speed": 12.98,
  "course": 265.27,
  "ignition": true,
  "simulated": true
}
```

Optional fields: `odometer`, `auth_token`, `gnss`
(`altitude_m`, `fix_valid`, `satellites_in_view`, `satellites_used`, `pdop`,
`hdop`, `vdop`, `constellations`, `satellites`).

Acceptance:

```json
{"type": "ack", "message_id": "3fa85f64-...", "status": "accepted", "duplicate": false, "received_at": "..."}
```

Validation failure:

```json
{"type": "error", "message_id": null, "error": {"code": "missing_fields", "message": "missing required fields: latitude"}}
```

Known error codes include `message_too_large`, `invalid_json`,
`invalid_message`, `missing_fields`, `unknown_fields`, `unsupported_protocol`,
`invalid_field`, `no_fix`.

## 7. Alerts and safety

| Method | Path | Body | Description |
| --- | --- | --- | --- |
| GET | `/alerts` | – | `{"alerts": [...], "unread": N, ...}` paginated with `limit`/`offset` |
| PATCH | `/alerts/{alert_id}` | – | Mark one alert read |
| PATCH | `/alerts/read-all` | – | Mark all alerts read |
| GET | `/api/safety/buses` | – | Buses selectable for SOS |
| POST | `/api/alerts/sos` | `SafetyAlertIn` | `201`; create an emergency report |
| GET | `/api/admin/safety-alerts` | – | List safety alerts (`status` filter) |
| GET | `/api/admin/safety-alerts/{alert_id}` | – | One safety alert |
| PATCH | `/api/admin/safety-alerts/{alert_id}/acknowledge` | `{"notes"?: "..."}` | Acknowledge |
| PATCH | `/api/admin/safety-alerts/{alert_id}/resolve` | `{"resolution_notes": "..."}` | Resolve |

`SafetyAlertIn`:

```json
{
  "bus_id": 1,
  "latitude": 13.037,
  "longitude": 77.622,
  "location_source": "gps",
  "reason": "Medical Emergency",
  "description": "Optional detail",
  "idempotency_key": "client-generated-key"
}
```

`location_source` is `gps`, `bus` or `unavailable`. `reason` is one of
`Unsafe Driving`, `Harassment / Threat`, `Medical Emergency`,
`Vehicle Breakdown / Off-route`.

## 8. WebSocket

### `GET /ws/locations` (WebSocket upgrade)

- No initial message is required; the server registers the client and starts
  forwarding events.
- Send the text frame `ping` to receive `{"type": "pong", ...}`.
- Telemetry, status transitions, alerts and safety events are pushed as JSON
  objects. The frontend reconnects automatically.

Example (browser):

```javascript
const socket = new WebSocket('ws://localhost:8000/ws/locations');
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);
  // vehicle, status, alert or pong payload
});
socket.addEventListener('open', () => socket.send('ping'));
```

Through the Vite dev server use the same origin with `/ws/locations`; Vite
proxies it to the backend with WebSocket support enabled.

## 9. Static frontend

| Method | Path | Description |
| --- | --- | --- |
| GET | `/assets/*` | Built JS/CSS assets from `frontend/vite/build/assets` |
| GET | `/{full_path:path}` | SPA fallback: serves `frontend/vite/build/index.html` for client routes |

`/logo.png` (a public compatibility symlink to `/images/logo.png`), `/tab.png`,
and the favicon/PWA icon files are static assets from `frontend/public/`.
API routes are registered before the catch-all, so they are never shadowed.

## 10. Quick checks

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/api/meta
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/docs
curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' -d '{}'      # 422
```

With `DEMO_AUTH_BYPASS=true` in development:

```bash
curl -s http://localhost:8000/buses
curl -s http://localhost:8000/api/tracking/latest
```
