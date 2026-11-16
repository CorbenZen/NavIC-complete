# Project structure

The repository is split into a Vite/React website, a Python backend organized
by framework responsibility, a standalone TCP application, and shared docs and
tests. Python package names use underscores so they remain importable packages.

```text
NavIC/
├── config/
│   ├── devices.demo.json          # demo IVTD device registry
│   └── devices.json               # legacy SIM demo registry
├── frontend/
│   ├── css-styles/global/         # application stylesheet
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── public/
│   │   ├── favicon/
│   │   │   └── tab.png
│   │   ├── icons/
│   │   ├── images/
│   │   │   └── logo.png
│   │   ├── logo.png
│   │   └── tab.png
│   ├── react-jsx/                 # React app, pages, components, context, hooks
│   ├── vite/                      # Vite config and generated production build
│   ├── leaflet-react/             # React Leaflet map, controls, markers, layers
│   └── javascript-services/       # HTTP and WebSocket clients
├── backend/
│   ├── python_fastapi/application # ASGI composition, routes, controllers, config
│   ├── python_pydantic/schemas    # request/response schema exports
│   ├── python_sqlalchemy/         # shared ORM facades, sessions and migrations
│   │   ├── database/              # connection, session, seed
│   │   ├── migrations/            # Alembic versions and env
│   │   └── models/                # SQLAlchemy model facades
│   ├── python_services/           # authentication, fleet, telemetry, alert, email
│   ├── python_authlib/            # Google OAuth integration
│   ├── python_asyncio/            # TCP receiver + WebSocket hub
│   ├── python_uvicorn/            # development entry point
│   ├── requirements.txt
│   ├── run.py
│   ├── alembic.ini
│   └── tests/
├── navic_tcp/                     # standalone TCP client/server
│   ├── api.py                     # FastAPI tracking API for TCP server
│   ├── auth.py                    # passwordless email auth + database sessions
│   ├── client.py                  # asyncio TCP client
│   ├── client_main.py             # CLI entry for device simulator
│   ├── db.py                      # SQLAlchemy base and session factory
│   ├── emailer.py                 # console/SMTP/Resend delivery
│   ├── env.py                     # environment loader
│   ├── fastapi_app.py             # shared FastAPI application
│   ├── manage_users.py            # admin user CLI
│   ├── models.py                  # SQLAlchemy models
│   ├── nmea.py                    # NMEA 0183 parser
│   ├── protocol.py                # JSON telemetry validation
│   ├── registry.py                # device registry loader
│   ├── reporting.py               # distance/trip/stoppage helpers
│   ├── schema.py                  # additive startup schema
│   ├── security.py                # scrypt, JWT, rate limiting
│   ├── server.py                  # asyncio TCP server
│   ├── server_main.py             # CLI entry for tracking server
│   ├── store.py                   # in-memory telemetry store
│   └── vehicle_status.py          # motion classification
├── docs/
│   ├── API_DOCUMENTATION.md
│   ├── AUDIT.md
│   ├── AUTHENTICATION_GUIDE.md
│   ├── BACKEND_GUIDE.md
│   ├── DATABASE_GUIDE.md
│   ├── DEVELOPMENT_GUIDE.md
│   ├── FEATURE_AUDIT.md
│   ├── FRONTEND_GUIDE.md
│   ├── GNSS_COMPATIBILITY.md
│   ├── PROJECT_STRUCTURE.md
│   ├── TCP_INTEGRATION.md
│   ├── TECH_STACK.md
│   └── TELEMETRY_GUIDE.md
├── tests/
│   ├── test_nmea.py
│   ├── test_startup.py
│   ├── test_store_api.py
│   └── test_tcp_system.py
├── pyproject.toml
├── .env.example
├── .gitignore
├── README.md
└── navic_dev.db
```