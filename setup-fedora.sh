#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

fail() { echo "Setup error: $*" >&2; exit 1; }

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  fail "Python 3 is missing. On Fedora run: sudo dnf install python3 python3-pip"
fi
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  fail "Python 3.11 or newer is required. On Fedora run: sudo dnf install python3 python3-pip"
fi
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  fail "Node.js and npm are missing. On Fedora run: sudo dnf install nodejs npm"
fi
if ! node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit((a === 20 && b >= 19) || (a === 22 && b >= 12) || a > 22 ? 0 : 1)' 2>/dev/null; then
  fail "Vite requires Node.js 20.19+ (22.12+ recommended). Update Node.js, then rerun this script."
fi

cd "$ROOT_DIR"
if [[ ! -d .venv-local ]]; then
  "$PYTHON" -m venv .venv-local || fail "Could not create the virtual environment. Install Fedora's python3-virtualenv package if needed."
fi
echo "Installing Python dependencies..."
.venv-local/bin/python -m pip install --upgrade pip
.venv-local/bin/python -m pip install -r backend/requirements-dev.txt

echo "Installing frontend dependencies from package-lock.json..."
(cd frontend && npm ci)

echo
echo "NavIC dependencies are ready. Start the app with: ./start-navic.sh"
