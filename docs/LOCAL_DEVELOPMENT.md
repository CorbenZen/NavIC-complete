# Local Fedora development

NavIC runs locally with React/Vite, FastAPI/Uvicorn, its existing TCP receiver,
and SQLite. No hosted backend or external database account is required.

## Fedora prerequisites

Use Python 3.11 or newer and Node.js 20.19+ (or 22.12+). To install Fedora
packages when missing:

```bash
sudo dnf install python3 python3-pip nodejs npm
```

Then install project dependencies once:

```bash
./setup-fedora.sh
```

The script creates `.venv-local`, installs `backend/requirements-dev.txt`, and
uses `npm ci` with the checked-in frontend lockfile.

## Start and stop

```bash
./start-navic.sh
```

The script starts the FastAPI backend and Vite frontend and stops both with
Ctrl+C. Local addresses:

- Frontend: <http://localhost:5173>
- Backend: <http://localhost:8000>
- OpenAPI docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>
- WebSocket: `ws://localhost:8000/ws/locations`
- TCP receiver: `127.0.0.1:5000`

The Vite proxy forwards relative API and WebSocket requests to `BACKEND_URL`
from the ignored project-root `.env` (default `http://localhost:8000`). The
same setting controls the local backend listener. Production should route the
same-origin `/api`, REST and `/ws` paths through its reverse proxy.

## Local database and existing records

SQLite lives at `~/.local/share/navic/navic.sqlite3` by default. Set
`NAVIC_DATA_DIR` to use another local directory. On first startup only, if
that database does not exist and the old project-root `navic_dev.db` exists,
NavIC uses SQLite's backup API to copy a consistent snapshot to the new path.
It verifies the copied database and leaves the original file untouched. An
existing destination database is never overwritten. Startup applies additive
schema initialization and retains records.

To explicitly inspect the active database location:

```bash
.venv-local/bin/python -c 'from navic_tcp.db import DATABASE_URL; print(DATABASE_URL)'
```

The console email provider captures local verification messages in the ignored
`dev-mail.jsonl` file. Configure SMTP in `.env` only when real email delivery
is needed. Google OAuth similarly requires local OAuth client credentials and
the callback `http://localhost:8000/auth/google/callback` in the provider
configuration.

## Run checks

```bash
.venv-local/bin/python -m pytest backend/tests tests
cd frontend && npm run build
```

The independent TCP simulator can be started while NavIC is running:

```bash
.venv-local/bin/python -m navic_tcp.client_main --host 127.0.0.1 --port 5000 --registry config/devices.demo.json --devices 6 --interval 1 --continuous
```
