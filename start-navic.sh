#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$ROOT_DIR/.venv-local/bin/python"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_PID=""
FRONTEND_PID=""

stop_services() {
  local pid
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]]; then wait "$pid" 2>/dev/null || true; fi
  done
}

on_interrupt() {
  echo
  echo "Stopping NavIC..."
  stop_services
  exit 130
}
trap on_interrupt INT TERM

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "NavIC Python environment not found. Run ./setup-fedora.sh first." >&2
  exit 1
fi
if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
  echo "Node.js and npm are required. Run ./setup-fedora.sh for Fedora setup." >&2
  exit 1
fi
if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Frontend dependencies are missing. Run ./setup-fedora.sh first." >&2
  exit 1
fi
if ! "$VENV_PYTHON" -c 'import fastapi, sqlalchemy, uvicorn' >/dev/null 2>&1; then
  echo "Backend dependencies are missing. Run ./setup-fedora.sh first." >&2
  exit 1
fi

cd "$ROOT_DIR"
export APP_ENV="${APP_ENV:-development}"
export API_HOST="${API_HOST:-127.0.0.1}"
if [[ -z "${BACKEND_URL:-}" || -z "${PORT:-}" ]]; then
  mapfile -t local_backend_settings < <("$VENV_PYTHON" - "$ROOT_DIR/.env" <<'PY'
import os, sys
from navic_tcp.env import load_env_file
load_env_file(sys.argv[1])
print(os.environ.get("BACKEND_URL", ""))
print(os.environ.get("PORT", ""))
PY
)
  [[ -n "${BACKEND_URL:-}" ]] || BACKEND_URL="${local_backend_settings[0]:-}"
  [[ -n "${PORT:-}" ]] || PORT="${local_backend_settings[1]:-}"
fi
export BACKEND_URL="${BACKEND_URL:-http://localhost:${PORT:-8000}}"
backend_port="$("$VENV_PYTHON" -c 'from urllib.parse import urlsplit; import os; print(urlsplit(os.environ["BACKEND_URL"]).port or 8000)')"
export PORT="${PORT:-$backend_port}"
export TCP_ENABLED="${TCP_ENABLED:-true}"

check_port_free() {
  local port="$1" name="$2"
  if ! "$VENV_PYTHON" -c 'import socket,sys; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(("127.0.0.1",int(sys.argv[1]))); s.close()' "$port"; then
    echo "$name port $port is busy; stop the other service or choose another port." >&2
    exit 1
  fi
}
check_port_free "$PORT" "Backend"
check_port_free 5173 "Frontend"

echo "Starting NavIC backend..."
"$VENV_PYTHON" backend/run.py &
BACKEND_PID=$!

echo "Starting NavIC frontend..."
(cd "$FRONTEND_DIR" && npm run dev -- --host 127.0.0.1 --port 5173 --strictPort) &
FRONTEND_PID=$!

echo
echo "NavIC is starting:"
echo "  Website:       http://localhost:5173"
echo "  Backend API:   $BACKEND_URL"
echo "  API docs:      $BACKEND_URL/docs"
echo "  Health check:  $BACKEND_URL/health"
echo "  TCP receiver:  127.0.0.1:${TCP_PORT:-5000}"
echo "Press Ctrl+C to stop both servers."

set +e
wait -n "$BACKEND_PID" "$FRONTEND_PID"
status=$?
set -e
if [[ $status -ne 130 ]]; then
  echo "A NavIC service exited (status $status); stopping the other service." >&2
fi
stop_services
exit "$status"
