# Backend Guide

The NavIC website backend is a FastAPI application served by Uvicorn. It is a
modular composition layer around the independent `navic_tcp` implementation:
route handler bodies, authentication, models and the telemetry pipeline live in
`navic_tcp`, while `backend/` owns configuration, domain routers, service access,
integrations and backend tests.

There is exactly one implementation of the API and one implementation of the
TCP protocol. `backend/` never imports `navic_tcp` code into a copy of itself,
and `navic_tcp/` never imports `backend/`.

## 1. Stack

| Concern | Technology |
| --- | --- |
| HTTP/WebSocket framework | FastAPI |
| ASGI server | Uvicorn |
| Validation / serialisation | Pydantic v2 |
| ORM | SQLAlchemy 2 |
| Database | Persistent local SQLite |
| Authentication | User ID + password, admin password, email magic link, Google OIDC, bearer tokens, database sessions |
| OAuth / OIDC | Authlib, HTTPX, google-auth |
| Email | Console capture, Resend or SMTP (`navic_tcp.emailer`) |
| Async | `asyncio` (TCP receiver, WebSocket fan-out, offline scans) |

## 2. Architecture

```text
backend/run.py                       development launcher (Uvicorn)
  └── backend.python_fastapi.application.main:app           ASGI entry
        ├── backend.python_fastapi.application.core.config  .env loading + environment defaults
        ├── backend.python_fastapi.application.api          modular routers
        │     └── _composition.py    copies route metadata from navic_tcp
        └── navic_tcp.fastapi_app    shared route bodies + lifespan + WebSocket
              ├── navic_tcp.db / models / schema
              ├── navic_tcp.auth / security / emailer
              ├── navic_tcp.reporting / vehicle_status
              └── navic_tcp.server / store / registry / protocol
```

### Why route metadata is copied

`navic_tcp/fastapi_app.py` is a single 3,300-line module with 86 registered
routes. Rewriting the handlers into `backend/` would duplicate live business
logic and break the requirement to keep `navic_tcp/` unmodified.

`backend/python_fastapi/application/api/routes/_composition.py` therefore copies each existing
`APIRoute` and `APIWebSocketRoute` into a domain router, preserving:

- path, HTTP methods and route name;
- response model, status code and `responses`;
- tags, summaries, descriptions, deprecation and schema inclusion;
- dependencies and OpenAPI parameters.

`backend/python_fastapi/application/main.py` then:

1. loads the project-root `.env`;
2. applies `Settings.apply_defaults()` so shared modules see development
   defaults even when variables are unset;
3. registers the domain routers, static mounts and the SPA fallback;
4. copies CORS/CSRF middleware, exception handlers and dependency overrides;
5. wraps `navic_tcp.fastapi_app.lifespan` so schema creation, the embedded TCP
   receiver and the offline-alert loop are started once.

A parity test (`backend/tests/test_backend_app.py`) asserts that the modular
app exposes exactly the same route set as the shared app (86 entries), plus the
middleware and exception handlers.

## 3. Directory reference

### `backend/run.py`

```bash
.venv-local/bin/python backend/run.py
```

Loads `.env`, applies defaults and starts Uvicorn with
`backend.python_fastapi.application.main:app` on `API_HOST:PORT` (defaults `0.0.0.0:8000`).
`uvicorn backend.python_fastapi.application.main:app --reload` is equivalent when a reload loop is
wanted.

### `backend/python_fastapi/application/main.py`

ASGI entry point. Exposes `app`, `backend_lifespan` and
`create_application()`, and adds two backend-level exception handlers:

- `SQLAlchemyError` → `503 {"detail": "database operation failed"}`;
- unhandled `Exception` → `500 {"detail": "internal server error"}`.

Both log the request method and path through the `navic.backend` logger.

### `backend/python_fastapi/application/_lazy.py`

`navic_tcp.fastapi_app` reads `APP_ENV`, `DATABASE_URL`, `JWT_SECRET` and other
values at import time. Importing a package executes its `__init__.py` first, so
eager re-exports in `backend/python_sqlalchemy/models/__init__.py` would import the shared app
before `.env` had been loaded. `_lazy.py` provides a module-level `__getattr__`
that resolves exports on first access. All package `__init__.py` files use it.

### `backend/python_fastapi/application/api/`

- `api/__init__.py` — `register_routes(app, source_routes)`:
  includes `auth`, `users`, `fleet`, `telemetry`, `alerts`, `websocket`, then
  mounts `/assets`, then includes `system` last so the `/{full_path:path}` SPA
  fallback cannot shadow API routes.
- `api/routes/__init__.py` — router registry and `GROUP_ORDER`.
- `api/routes/_composition.py` — route copying helpers.
- `api/routes/auth.py` — `/auth/*` path operations.
- `api/routes/users.py` — `/api/user*`, `/api/users*`, `/api/feedback`,
  `/api/support`, `/api/bus-pass*`, `/api/admin/bus-passes`.
- `api/routes/fleet.py` — vehicles, devices, drivers, routes, geofences,
  settings, trips, dashboard, reports and audit.
- `api/routes/telemetry.py` — `/api/tracking/latest`,
  `/buses/{bus_id}/history`, `/api/devices/{device_id}/telemetry/latest`.
- `api/routes/alerts.py` — `/alerts*`, `/api/alerts/sos`, `/api/safety/buses`,
  `/api/admin/safety-alerts*`.
- `api/routes/websocket.py` — `/ws/locations`.
- `api/routes/system.py` — `/health`, `/api/meta`, SPA fallback.

### `backend/python_fastapi/application/core/`

| Module | Contents |
| --- | --- |
| `config.py` | `Settings`, `PROJECT_ROOT`, `load_environment()`, `get_settings()`, `DEFAULT_DATABASE_URL`, `DEFAULT_FRONTEND_DIST` |
| `security.py` | re-exports `hash_password`, `verify_password`, `password_needs_rehash`, `issue_token`, `verify_token`, `token_hash`, `new_secret`, `LoginRateLimiter`, `SlidingWindowRateLimiter`; adds `issue_access_token()` and `verify_access_token()` |
| `dependencies.py` | `get_db()`, `get_app_settings()`, and re-exports `current_user`, `management_user`, `admin_user` |

`Settings` fields include `app_env`, `database_url`, `jwt_secret`,
`cors_origins`, `tcp_enabled/host/port`, `device_registry`, `email_provider`,
`frontend_url`, `backend_url`, `frontend_dist`, `google_client_id/secret/
redirect_uri`, `cookie_secure`, session/magic-link TTLs, `demo_auth_bypass`,
`api_host`, `api_port` and `log_level`. `websocket_url` derives `ws://` or
`wss://` from `backend_url`.

`apply_defaults()` uses `os.environ.setdefault`, so an exported variable or a
`.env` value always wins over the built-in default.

### `backend/python_sqlalchemy/database/`

| Module | Contents |
| --- | --- |
| `base.py` | `Base` (the shared SQLAlchemy declarative base) |
| `connection.py` | `engine`, `DATABASE_URL`, `init_database()`, `database_reachable()`, schema helpers |
| `session.py` | `SessionLocal`, `get_db()` dependency, `session_scope()` transaction context |
| `seed.py` | Idempotent demo-fleet seeder |

`session_scope()` commits on success, rolls back on exception and always closes
the session:

```python
from backend.python_sqlalchemy.database import session_scope

with session_scope() as db:
    db.add(record)
```

### `backend/python_sqlalchemy/models/`

Domain re-exports of the 19 models defined in `navic_tcp/models.py`:

| Module | Models |
| --- | --- |
| `user.py` | `User`, `UserPreferences`, `AuthSession`, `MagicLinkToken`, `GoogleOAuthTransaction`, `StudentBusPass`, `Feedback`, `SupportTicket` |
| `fleet.py` | `Bus`, `Driver`, `Route`, `Geofence`, `TrackingDevice` |
| `telemetry.py` | `LocationHistory`, `DeviceGeofenceState` |
| `alert.py` | `Alert`, `SafetyAlert` |
| `system.py` | `SystemSetting`, `AuditLog` |

### `backend/python_pydantic/schemas/`

Re-exports the 25 Pydantic classes:

| Module | Classes |
| --- | --- |
| `auth.py` | `LoginIn`, `AdminLoginIn`, `MagicLinkIn`, `VerifyMagicLinkIn` |
| `user.py` | `UserProfileIn`, `PreferencesIn`, `FeedbackIn`, `SupportIn`, `TicketStatusIn`, `BusPassIssueIn` |
| `fleet.py` | `BusIn`, `BusOut`, `DriverIn`, `DriverOut`, `RouteIn`, `RouteOut`, `RouteStop`, `GeofenceIn`, `GeofenceOut`, `SettingIn` |
| `telemetry.py` | `DeviceIn`, `DeviceOut` |
| `alert.py` | `SafetyAlertIn`, `SafetyAcknowledgeIn`, `SafetyResolveIn` |

### `backend/python_services/`

| Module | Responsibility |
| --- | --- |
| `auth_service.py` | Magic-link creation/verification, database sessions, CSRF cookies, session expiry |
| `fleet_service.py` | Transactional CRUD for buses, drivers, routes, geofences and devices; fleet counts |
| `telemetry_service.py` | NDJSON decode/ack/error encoding, ingestion via the shared pipeline, latest-point and history queries |
| `alert_service.py` | Offline-alert generation, status-transition evaluation, alert read state and pagination |
| `email_service.py` | Magic-link delivery through the configured provider, delivery status |

`fleet_service` uses explicit commit/rollback (not autocommit):

```python
from backend.python_sqlalchemy.database import SessionLocal
from backend.python_services import fleet_service

with SessionLocal() as db:
    bus = fleet_service.create_record(
        db, Bus, vehicle_id="BUS-01", registration_number="KA01AB1234"
    )
    fleet_service.update_record(db, Bus, bus.id, driver_name="A. Driver")
```

### `backend/python_fastapi/application/integrations/`

- `google_oauth.py` — `GoogleOAuthSettings`, `build_client()` (Authlib
  `AsyncOAuth2Client`), `create_authorization_request()` with state/nonce/PKCE,
  and async wrappers around the shared code exchange, certificate fetch and
  `google-auth` ID-token verification.
- `tcp_receiver.py` — `TCPTelemetryBridge`:

```python
from backend.python_asyncio.tcp.tcp_receiver import create_bridge

bridge = create_bridge()
ack = await bridge.send(message)   # validated by navic_tcp.protocol, sent via send_once
online = await bridge.probe()
```

The bridge validates a message by encoding and decoding it with the real
protocol functions, then sends it to the existing TCP server with
`navic_tcp.client.send_once`. It does not implement a second server or alter the
wire format.

### `backend/python_utils/helpers.py`

`utc_now`, `as_utc`, `isoformat`, `parse_bool`, `clamp`, `page_params`,
`json_default`, `to_json`.

## 4. Configuration

| Setting | Variable | Default |
| --- | --- | --- |
| Runtime mode | `APP_ENV` | `development` |
| Database | `DATABASE_URL` | `sqlite:///./navic_dev.db` |
| Signing secret | `JWT_SECRET` | generated per process in development; required outside development |
| Token TTL | `JWT_TTL_SECONDS` | `3600` |
| API host/port | `API_HOST`, `PORT` | `0.0.0.0`, `8000` |
| Backend public URL | `BACKEND_URL` | `http://localhost:{PORT}` |
| Frontend public URL | `FRONTEND_URL` | `http://localhost:5173` |
| CORS | `CORS_ORIGINS` (comma-separated) | localhost dev origins |
| Embedded TCP receiver | `TCP_ENABLED`, `TCP_HOST`, `TCP_PORT` | `true`, `127.0.0.1`, `5000` |
| Device registry | `DEVICE_REGISTRY` | `config/devices.demo.json` |
| Built SPA directory | `FRONTEND_DIST` | `frontend/vite/build` |
| Google OIDC | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | unset |
| Email | `EMAIL_PROVIDER`, `EMAIL_FROM`, `EMAIL_CAPTURE_FILE`, `SMTP_*`, `EMAIL_API_KEY` | console capture |
| Sessions | `SESSION_TTL_MINUTES`, `COOKIE_SECURE`, `COOKIE_SAMESITE` | `720`, `false`, `lax` |
| Magic links | `MAGIC_LINK_TTL_MINUTES`, `MAGIC_LINK_*_LIMIT` | `15` |
| Demo bypass | `DEMO_AUTH_BYPASS` | `false` |

The annotated templates are the root `.env.example` and `backend/.env.example`.
Never commit real secrets.

## 5. Authentication

| Method | Endpoint | Notes |
| --- | --- | --- |
| User ID registration | `POST /api/auth/register` | student/teacher account; unique `user_id`, scrypt password; no email |
| User ID login | `POST /api/auth/login` | verifies password, or the configured admin email; sets session + CSRF cookies |
| Session state | `GET /api/auth/me` | bearer token or `navic_session` cookie |
| Logout | `POST /api/auth/logout` | revokes the session row and clears cookies |
| Admin password | `POST /auth/admin-login` | scrypt password hash, login rate limiting |
| Standard password | `POST /auth/login` | legacy email-password contract for API clients |
| Magic link request | `POST /auth/magic-link` | single-use token, per-IP and per-email limits |
| Magic link verify | `POST /auth/magic-link/verify` | sets opaque session + CSRF cookies |
| Google OIDC | `GET /auth/google/login`, `/auth/google/callback` | state, nonce, PKCE, ID-token verification |
| Session state (legacy) | `GET /auth/me` | bearer token or `navic_session` cookie |

- Passwords use salted `scrypt` (`hash_password`/`verify_password`);
  legacy 64-character SHA-256 hashes are still accepted and flagged by
  `password_needs_rehash`.
- Bearer tokens are HMAC-signed with `SECRET` (`issue_token`/`verify_token`);
  `backend.python_fastapi.application.core.security` adds `issue_access_token`/`verify_access_token`.
- Cookie sessions are opaque random tokens stored as hashes in `auth_sessions`,
  with a separate CSRF token stored hashed and compared using `hmac.compare_digest`.
- Cookie-authenticated state changes require `X-CSRF-Token` matching the
  `navic_csrf` cookie and the stored CSRF hash.
- Authorisation levels are exposed by `current_user`, `management_user` and
  `admin_user`.
- In development only, `DEMO_AUTH_BYPASS=true` returns a demo administrator.
  This is read from the environment by `navic_tcp.fastapi_app` at import time.

## 6. Telemetry pipeline

```text
device --NDJSON--> navic_tcp.server.TelemetryServer (asyncio, port 5000)
                      ├── navic_tcp.protocol.decode_telemetry  (validation)
                      ├── store/registry bookkeeping
                      └── navic_tcp.fastapi_app.on_telemetry
                            ├── LocationHistory row (SQLAlchemy)
                            ├── geofence evaluation
                            ├── vehicle-status classification
                            └── WebSocket hub publish -> /ws/locations
```

- One newline-delimited JSON object per message; the maximum frame is 64 KiB.
- Required fields and ranges are enforced by `decode_telemetry`; unknown fields
  are rejected.
- Duplicate `message_id`s are acknowledged as duplicates instead of stored.
- The backend's `telemetry_service.decode_frame`, `encode_ack` and `encode_error`
  are the same functions used by the transport tests.
- `telemetry_service.ingest()` calls the shared `on_telemetry` coroutine, so a
  backend-originated frame is persisted and broadcast exactly like a TCP frame.
- `/api/tracking/latest`, `/buses/{bus_id}/history` and
  `/api/devices/{device_id}/telemetry/latest` read stored fixes.

## 7. WebSocket

`GET /ws/locations` upgrades to a WebSocket. It:

- registers the client with the shared broadcast hub;
- accepts a text `"ping"` and replies `{"type": "pong", ...}`;
- forwards every telemetry/status event published by the TCP pipeline;
- removes the client on disconnect.

The frontend connects with `locationSocketUrl()` from
`frontend/javascript-services/api.js`.

## 8. Errors and responses

- Request validation failures return FastAPI's `422` structure with `detail`.
- Domain failures raise `HTTPException` with `{"detail": "..."}`.
- Database failures return `503`; unexpected failures return `500`.
- Successful list endpoints return JSON arrays or objects exactly as the shared
  handlers define them (for example `GET /devices` returns
  `{"devices": [...]}`).
- `/health` returns status, database, TCP state, environment, version and the
  number of WebSocket clients.
- `/api/meta` returns the application version, environment, authentication
  methods, report names, GNSS capability and simulation notice.

## 9. Tests

```bash
.venv-local/bin/python -m unittest discover -s backend/tests -t . -v   # 120 tests
.venv-local/bin/python -m unittest discover -s tests -v                # 44 tests (TCP)
```

`backend/tests/test_backend_app.py` covers:

- exact route parity, middleware and exception-handler preservation;
- OpenAPI coverage and `/docs`;
- `/health` including database reachability;
- static assets and the SPA fallback;
- password hashing, bearer-token round trips, 401 without credentials, 422
  validation;
- fleet, telemetry and alert endpoints;
- service-level CRUD, duplicate-insert rollback and connectivity helpers;
- telemetry frame decoding/acknowledgement and invalid-frame rejection;
- WebSocket ping/pong;
- settings defaults and environment overrides.

The remaining backend modules cover reports, magic-link auth, security, schema
migration, vehicle status and student/safety services.

## 10. Adding backend code

| Task | Location |
| --- | --- |
| New HTTP endpoint or WebSocket handler | `navic_tcp/fastapi_app.py` (shared implementation), then map its path family in `backend/python_fastapi/application/api/routes/` |
| New domain router | `backend/python_fastapi/application/api/routes/<domain>.py` + registry in `routes/__init__.py` |
| New pure business rule | `navic_tcp/reporting.py`, `vehicle_status.py` or a new module in `navic_tcp/` |
| New database table/column | `navic_tcp/models.py` + additive `navic_tcp/schema.py` |
| New request/response schema | `navic_tcp/fastapi_app.py`, then re-export in `backend/python_pydantic/schemas/` |
| New backend default | `backend/python_fastapi/application/core/config.py` + both `.env.example` files |
| New service helper | `backend/python_services/` |
| New integration | `backend/python_fastapi/application/integrations/` |
| New backend test | `backend/tests/` |

Keep `navic_tcp/` importable on its own and never import `backend` from it.
