#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="$PROJECT_DIR/.runtime"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "[error] Python 3.10+ was not found."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[error] npm was not found. Install Node.js 18+ first."
  exit 1
fi

if ! node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 18 ? 0 : 1)"; then
  echo "[error] Node.js 18+ is required."
  exit 1
fi

"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("[error] Python 3.10+ is required.")
PY

mkdir -p "$RUNTIME_DIR"

if [ ! -x "$BACKEND_DIR/.venv/bin/python" ]; then
  echo "[setup] Creating the backend virtual environment..."
  "$PYTHON" -m venv "$BACKEND_DIR/.venv"
fi
VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"

if ! "$VENV_PYTHON" -c "import fastapi, chromadb, pandas, reportlab" >/dev/null 2>&1; then
  echo "[setup] Installing backend dependencies..."
  "$VENV_PYTHON" -m pip install -r "$BACKEND_DIR/requirements.txt"
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "[setup] Installing frontend dependencies..."
  (cd "$FRONTEND_DIR" && npm ci --no-fund --no-audit)
fi

if [ -f "$RUNTIME_DIR/backend.pid" ] || [ -f "$RUNTIME_DIR/frontend.pid" ]; then
  "$PROJECT_DIR/stop.sh" >/dev/null 2>&1 || true
fi

port_in_use() {
  "$PYTHON" - "$1" <<'PY'
import socket
import sys

with socket.socket() as sock:
    sock.settimeout(0.2)
    raise SystemExit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

for port in 8000 5173; do
  if port_in_use "$port"; then
    echo "[error] Port $port is already in use. Stop that service and retry."
    exit 1
  fi
done

echo "[1/2] Starting backend at http://localhost:8000"
(
  cd "$BACKEND_DIR"
  nohup "$VENV_PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    >"$RUNTIME_DIR/backend.log" 2>&1 &
  echo $! >"$RUNTIME_DIR/backend.pid"
)

echo "[2/2] Starting frontend at http://localhost:5173"
(
  cd "$FRONTEND_DIR"
  nohup "$FRONTEND_DIR/node_modules/.bin/vite" --host 0.0.0.0 \
    >"$RUNTIME_DIR/frontend.log" 2>&1 &
  echo $! >"$RUNTIME_DIR/frontend.pid"
)

echo "[wait] The knowledge base is being initialized for the first run..."
READY=0
for _ in $(seq 1 120); do
  if "$PYTHON" - <<'PY' >/dev/null 2>&1
import urllib.request

for url in ("http://localhost:8000/api/health", "http://localhost:5173"):
    with urllib.request.urlopen(url, timeout=1) as response:
        if response.status != 200:
            raise SystemExit(1)
PY
  then
    READY=1
    break
  fi
  sleep 1
done

if [ "$READY" -ne 1 ]; then
  echo "[error] Startup timed out. Check .runtime/backend.log and .runtime/frontend.log."
  "$PROJECT_DIR/stop.sh" >/dev/null 2>&1 || true
  exit 1
fi

echo "[ok] Open http://localhost:5173"
if command -v open >/dev/null 2>&1; then
  open http://localhost:5173
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open http://localhost:5173 >/dev/null 2>&1 || true
fi
