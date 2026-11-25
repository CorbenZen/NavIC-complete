#!/bin/sh
# Production start command for the NavIC container (used by Render).
#
# 1. Apply additive Alembic migrations to the configured DATABASE_URL.
# 2. Optionally run the idempotent demo-fleet seed (SEED_DEMO_DATA=true). The
#    seed only creates/updates demo buses, devices, drivers, routes and one
#    geofence; it never deletes records, creates accounts or fabricates telemetry.
# 3. Start FastAPI/Uvicorn on $PORT.
set -eu

cd "$(dirname "$0")/.."

echo "Applying database migrations..."
python -m alembic -c backend/alembic.ini upgrade head

case "$(printf '%s' "${SEED_DEMO_DATA:-false}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on)
    echo "Seeding demo fleet (idempotent)..."
    python -m backend.python_sqlalchemy.database.seed
    ;;
esac

echo "Starting NavIC API on port ${PORT:-8000}..."
exec python backend/run.py
