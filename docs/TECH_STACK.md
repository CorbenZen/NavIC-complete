# NavIC technology stack

NavIC has three cooperating parts: a React/Vite fleet console, a FastAPI
website backend, and an independently runnable TCP telemetry application.

| Technology | Use | Implementation |
| --- | --- | --- |
| JavaScript, React 19, JSX | Operations console, pages, state and forms | `frontend/react-jsx/` |
| Vite 8 | Dev server and production bundling | `frontend/vite/vite.config.js`, `frontend/package.json` |
| Leaflet, React Leaflet | Fleet location maps and markers | `frontend/leaflet-react/`, `frontend/leaflet-react/components/` |
| lucide-react, qrcode.react | Interface icons and QR rendering | Frontend components |
| CSS | Layout, themes, responsive and component styling | `frontend/css-styles/global/styles.css` |
| Python, FastAPI, Uvicorn | HTTP API, docs, SPA hosting and WebSockets | `backend/python_fastapi/application/`, `backend/run.py` |
| Pydantic | Request and response validation | `navic_tcp/schema.py`, `backend/python_pydantic/schemas/` |
| SQLAlchemy 2 | ORM and database access | `navic_tcp/models.py`, `navic_tcp/db.py`, `backend/python_sqlalchemy/database/` |
| SQLite | Persistent local application data | `.env.example`, `navic_tcp/db.py`, `navic_tcp/local_paths.py` |
| Alembic | Versioned additive schema evolution | `backend/python_sqlalchemy/migrations/` |
| Authlib, HTTPX, google-auth | Google OAuth integration | `backend/python_authlib/google_oauth/google_oauth.py` |
| hashlib, secrets, hmac | Password/token/verification security | `navic_tcp/security.py`, `backend/python_fastapi/application/core/security.py` |
| asyncio | Concurrent TCP, HTTP and WebSocket handling | `navic_tcp/server.py`, `backend/python_asyncio/websocket/` |
| smtplib, email, urllib | Email link delivery and URL utilities | `navic_tcp/emailer.py`, backend email/auth services |

Exact resolved frontend package versions are recorded in
`frontend/package-lock.json`. Python requirements use bounded compatible
version ranges in `backend/requirements.txt`; install into the selected Python
3.11+ environment to resolve them.

## Implemented scope

SQLite is the configured local database. SQLAlchemy models and migrations keep
database access centralized for future database options.
The website has authenticated fleet, vehicle, telemetry, alert, settings,
reporting and user endpoints. The frontend uses the FastAPI API and a
reconnecting WebSocket for live updates. Google OAuth is optional and requires
provider credentials; email sign-in links can use configured SMTP or the local
development mail capture. The TCP listener and simulator remain independently
runnable.

Leaflet is used for geographic fleet views. The current implementation does not
claim a GNSS receiver or NavIC constellation-specific positioning capability;
it consumes validated location telemetry and records fix provenance.
