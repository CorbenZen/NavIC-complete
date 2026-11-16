# NavIC — College Bus Tracking Management System

NavIC (CBTMS) is a college fleet operations prototype. It brings together a React and Leaflet dashboard, a FastAPI service, a local SQLite store, and a TCP receiver for vehicle telemetry. Operators can view fleet positions, review trips and reports, and manage vehicles, devices, routes, geofences, and alerts.

> **Prototype data:** No IVTD hardware is connected. Bundled buses and telemetry are simulator data and remain labelled as simulated; they are not live fleet records.
---
## Run the complete application

Requirements: Python 3.11+, Node.js, and npm. On Fedora, the setup script installs project dependencies and prepares the local environment:

```bash
./setup-fedora.sh
./start-navic.sh
```

Open <http://localhost:5173>. The API health check is <http://localhost:8000/health> and interactive API docs are at <http://localhost:8000/docs>. Stop both services with Ctrl+C. Local SQLite data is stored under `~/.local/share/navic/` by default.

To configure local settings, copy `.env.example` to `.env` and change only the values needed for your environment. The development proxy uses `BACKEND_URL` (default `http://localhost:8000`). Keep credentials and generated secrets out of source control.

To provision another administrator on this local database, run the command below as an existing operator. It prompts for a password and stores only a salted hash; never add the password or hash to GitHub.

```bash
.venv-local/bin/python -m navic_tcp.manage_users bootstrap-admin \
  --email admin2@example.edu --user-id admin2@example.edu --force
```

## Run the demo simulator

With the application running, start a separate terminal and run:

```bash
.venv-local/bin/python -m navic_tcp.client_main --devices 6 --continuous
```

Simulator records are explicitly marked as simulated. The real IVTD wire protocol and hardware behavior have not been confirmed.

## Development checks

```bash
.venv-local/bin/pytest backend/tests tests
.venv-local/bin/ruff check backend navic_tcp tests scripts
cd frontend && npm ci && npm run check && npm run smoke
```

The smoke test needs the backend and Playwright browser prerequisites described in the frontend repository guide.

## Repository map

- `backend/` — FastAPI routes, SQLAlchemy persistence, and additive migrations.
- `navic_tcp/` — TCP receiver, telemetry validation, simulator, and shared services.
- `frontend/` — React/Vite application and Leaflet map.
- `tests/`, `backend/tests/` — Python test suites.
- `docs/` — architecture, API, setup, and operational notes.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the data flow and [docs/API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md) for API details.
