# Account creation and sign-in report

## Cause and changes

The saved frontend environment had `VITE_API_BASE_URL` targeting `localhost:8001`. That port belongs to `navic_tcp/api.py`, a GET-only tracking API; its `TrackingApiServer.dispatch('POST', ...)` returned `405` with `{"error":{"code":"method_not_allowed","message":"only GET is supported"}}`. The FastAPI website backend is configured for port 8000 and its generated OpenAPI lists `POST` for both `/api/auth/register` and `/api/auth/login`. The failure comes from the selected target: FastAPI registers the POST route, while the tracking API on port 8001 accepts GET only. The legacy browser request itself could not be captured because browser networking is restricted in this session; see NOT TESTED below. Direct POST curls to ports 8000 and 5173 returned curl error 7 (connection refused), so neither produced an HTTP status or response body.

The browser now sends relative API and WebSocket URLs. Vite reads the project-root `BACKEND_URL` (default `http://localhost:8000`) for its dev proxy, and the local backend derives its development listener port from that same setting. The 405 message no longer asks users to refresh. The signup result navigates to sign-in with the User ID prefilled and the banner `Account created. Sign in with your User ID.` No password is placed in the URL.

ID/password accounts use the existing SQLAlchemy `users` table and salted scrypt hasher. The additive `second_name` column is backfilled from `last_name` and kept aligned for new registrations. User IDs and student USNs keep their normalized unique indexes, new registrations use role `viewer`, and input cannot set a role. Unknown IDs and incorrect passwords now both return HTTP 401 with `Incorrect User ID or password`. Cookie lookup precedes demo fallback, allowing a real account session to replace the synthetic demo identity. Session establishment still updates `last_login_at` and appends the existing audit row; logout revokes the session.

## Files changed

- Backend: `backend/python_fastapi/application/core/config.py`, `backend/python_fastapi/application/controllers/auth_controller.py`, new `backend/python_sqlalchemy/migrations/versions/0008_user_second_name.py`, `navic_tcp/fastapi_app.py`, `navic_tcp/models.py`, `navic_tcp/schema.py`, and registration/schema migration tests.
- Frontend: `frontend/javascript-services/api.js`, both Vite configs, `frontend/react-jsx/App.jsx`, auth Login, FleetContext, Shell, Sidebar, ErrorBanner and Trips components, global CSS, and `frontend/scripts/smoke_routes.mjs`.
- Setup/docs: `.env.example`, `frontend/.env.example`, `frontend/.env` (removed the stale API override), `start-navic.sh`, README, local/frontend docs and manual tests.

## Evidence

- `DEMO_AUTH_BYPASS=false .venv-local/bin/pytest backend/tests/test_registration.py backend/tests/test_schema_migration.py -q`: `26 passed, 7 subtests passed`.
- `DATABASE_URL=sqlite:////tmp/navic_auth_migration.sqlite3 ... alembic upgrade head`, then `downgrade -1 && upgrade head`: the new revision applied, downgraded, and reapplied on a scratch SQLite database.
- `app.openapi()` listed `POST` for `/api/auth/register` and `/api/auth/login`.
- `npm run check`: exit 0; ESLint reported 0 errors and 36 warnings; Vite built successfully.
- `npm run smoke`: NOT TESTED in a browser. Chromium and Firefox executables are absent; output was `SMOKE FAIL (12 routes × 2 themes × 2 browsers × 4 viewports)` with both browser launches reported unavailable.

## NOT TESTED / limitations

- Live PostgreSQL persistence is NOT TESTED. `psql` and `pg_isready` are not installed, and the configured database dialect reported by `get_settings()` is `sqlite`. Tests use an isolated in-memory SQLite database. Production configuration already requires a PostgreSQL `DATABASE_URL`, but this session could not inspect a real PostgreSQL row or configure credentials.
- Browser capture of the old request method, full URL, status and response body is NOT TESTED. Both browser executables are missing, the Vite bind returned `listen EPERM`, and the sandbox could not connect to local HTTP ports. The source-level dispatch check and OpenAPI route listing above are command output, not a live browser request.
- Chromium/Firefox register → reload → sign out → sign in → fresh context with saved cookies is NOT TESTED. The opt-in flow is in `frontend/scripts/smoke_routes.mjs` and uses `SMOKE_REGISTER_FLOW=1`; run it against a disposable database.
- Full `pytest backend/tests tests` is NOT TESTED to completion: it collected 211 tests, passed the first 13, then blocked in `backend/tests/test_backend_app.py` while `TestClient.__enter__()` waited for app startup. The focused account/schema suites completed as noted above.

To inspect a saved row on a PostgreSQL-configured deployment (replace the sample ID), run this query. It uses the real `users` columns and prints only the first 16 hash characters:

```bash
psql "$DATABASE_URL" --set=user_id='USER_ID_HERE' --command="SELECT user_id, usn, first_name, second_name, account_type, role, left(password_hash, 16) || '…' AS password_hash_prefix, created_at, last_login_at FROM users WHERE lower(trim(user_id)) = lower(:'user_id');"
```

The relevant environment variable names are `DATABASE_URL`, `BACKEND_URL`, and `DEMO_AUTH_BYPASS`; this report contains no values for secrets.
