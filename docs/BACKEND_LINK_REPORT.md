# Backend link report

## Diagnosis

The frontend override targeted port 8001, while the FastAPI website service defaults to port 8000. The configured `8001` service code is a GET-only telemetry API, which explains both a `POST /api/auth/register` 405 and the trip-history API connection failure. `app.openapi()` reported `POST` on `/api/auth/register` and `/api/auth/login`. CORS was not the cause: runtime settings listed both `http://localhost:5173` and `http://127.0.0.1:5173`.

The classification is **wrong backend target/port**. At the time of the port probes, neither port had a reachable listener. A separate isolated-backend launch reached `Application startup complete` and logged Uvicorn on `0.0.0.0:8000`, so the inspected code did not crash at startup. The successful startup used a scratch SQLite database, not the user's configured database.

## Changes

- Removed the browser-side host override. API and WebSocket calls now use relative `/api` and `/ws` paths.
- Main and test Vite configs both read the project-root `BACKEND_URL`; the default target is FastAPI on port 8000. `start-navic.sh` loads that setting safely, aligns the backend port, checks the two local ports before launch, and prints the resolved URLs.
- Backend development settings derive the Uvicorn port from `BACKEND_URL`.
- `FleetContext` owns a shared `/health` check: 15-second checks, exponential backoff up to 60 seconds, hidden-tab pause, and immediate retry. The topbar and sidebar share API + WebSocket status. Offline state shows one shell banner with Retry and the attempted health URL; network failures no longer clear the trip rows or repeat as page error banners. Trips reload after API recovery without a page reload.
- README and local setup documentation now describe `BACKEND_URL` and production same-origin reverse-proxy paths.

## Files changed

- Backend and launcher: `backend/python_fastapi/application/core/config.py`, `start-navic.sh`.
- Frontend: `frontend/javascript-services/api.js`, both Vite configs, FleetContext, Shell, Sidebar, shared ErrorBanner, Trips, global styles, and the Playwright smoke script.
- Setup/docs: `.env.example`, frontend env examples, README, local development/frontend guides, manual tests, and the authentication report.

## Command evidence

- `ss -ltnp`: `Cannot open netlink socket: Operation not permitted`; process-listener inspection is NOT TESTED in this sandbox.
- `curl -i --max-time 2 http://localhost:8000/health` and the same request to port 8001 both returned curl error 7, connection refused, before the isolated server launch. After launching Uvicorn, curl from another sandbox command was blocked with `Operation not permitted`.
- Backend isolated launch output: `Application startup complete` and `Uvicorn running on http://0.0.0.0:8000`; it was stopped by the command timeout. No TCP receiver was enabled.
- `npm run dev -- --host 127.0.0.1 --port 5173 --strictPort`: Vite exited with `Error: listen EPERM: operation not permitted 127.0.0.1:5173`. The proxy could not be exercised over HTTP.
- The Vite source uses `BACKEND_URL`; `frontend/.env` no longer contains `VITE_API_BASE_URL`. A targeted source search found no hard-coded backend host in the browser API, React, or CSS sources.
- `npm run check`: exit 0; 0 lint errors (36 warnings) and Vite build success.
- `curl -i -X POST` against the direct FastAPI URL on 8000 and the Vite URL on 5173 both returned curl error 7 (connection refused), with no HTTP status/body. `npm run smoke`: browser checks NOT TESTED. Playwright could not find Chromium at its configured cache path or Firefox at its configured cache path; the smoke command exited 1 with both launch failures.
- Focused backend registration/schema tests: `26 passed, 7 subtests passed`. Full `pytest backend/tests tests` collected 211 tests and was stopped after blocking in `TestClient.__enter__()` in `test_backend_app.py`; it is NOT TESTED to completion.

## NOT TESTED

- Live request/recovery behavior and screenshots in Chromium and Firefox.
- The API proxy through both localhost origins. The Vite server could not bind in this sandbox; `ss` cannot inspect listeners here.
- Browser recovery on `/trips` without reloading. The smoke scenario is implemented but could not run without browsers and reachable local servers.
- A real PostgreSQL account row; local configuration is SQLite and PostgreSQL tools/services are unavailable.

For a local repeat, copy `.env.example` to `.env`, set `BACKEND_URL` and `DEMO_AUTH_BYPASS=false`, apply `.venv-local/bin/alembic -c backend/alembic.ini upgrade head`, then run `./start-navic.sh`. Use `docs/MANUAL_TESTS.md` for the offline/recovery and account browser steps.
