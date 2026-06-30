#!/usr/bin/env bash
set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8002}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT/frontend"
PID_FILE="$ROOT/.dev-pids.json"
BACKEND_OUT="$ROOT/backend-dev-${BACKEND_PORT}.out.log"
BACKEND_ERR="$ROOT/backend-dev-${BACKEND_PORT}.err.log"
FRONTEND_OUT="$ROOT/frontend-dev-${FRONTEND_PORT}.out.log"
FRONTEND_ERR="$ROOT/frontend-dev-${FRONTEND_PORT}.err.log"

stop_port() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [ -n "$pids" ]; then
      kill $pids 2>/dev/null || true
    fi
  fi
}

wait_url() {
  local url="$1"
  for _ in $(seq 1 90); do
    if command -v curl >/dev/null 2>&1 && curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

cd "$ROOT"

echo "Preparing CS Gap Assist dev server..."
if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import importlib.util
missing = [m for m in ["fastapi", "uvicorn", "pydantic_settings", "requests", "numpy", "httpx"] if importlib.util.find_spec(m) is None]
raise SystemExit(1 if missing else 0)
PY
then
  echo "Installing backend dependencies..."
  "$PYTHON_BIN" -m pip install -e ".[rag,xfyun]"
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "Installing frontend dependencies..."
  npm install --prefix "$FRONTEND_DIR"
fi

echo "Releasing ports $BACKEND_PORT and $FRONTEND_PORT..."
stop_port "$BACKEND_PORT"
stop_port "$FRONTEND_PORT"
sleep 2

rm -f "$BACKEND_OUT" "$BACKEND_ERR" "$FRONTEND_OUT" "$FRONTEND_ERR"

echo "Starting backend on 0.0.0.0:$BACKEND_PORT..."
"$PYTHON_BIN" -m uvicorn backend.main:app --host 0.0.0.0 --port "$BACKEND_PORT" >"$BACKEND_OUT" 2>"$BACKEND_ERR" &
backend_pid=$!

echo "Starting frontend on 0.0.0.0:$FRONTEND_PORT..."
npm run dev --prefix "$FRONTEND_DIR" -- --host 0.0.0.0 --port "$FRONTEND_PORT" >"$FRONTEND_OUT" 2>"$FRONTEND_ERR" &
frontend_pid=$!

"$PYTHON_BIN" - <<PY
import json
from pathlib import Path
Path(r"$PID_FILE").write_text(json.dumps({
    "backend": $backend_pid,
    "frontend": $frontend_pid,
    "backendPort": $BACKEND_PORT,
    "frontendPort": $FRONTEND_PORT,
    "url": "http://localhost:$FRONTEND_PORT/"
}, indent=2), encoding="utf-8")
PY

if ! wait_url "http://127.0.0.1:$FRONTEND_PORT/api/v1/health"; then
  echo "Startup did not become healthy in time."
  echo "Backend log:  $BACKEND_ERR"
  echo "Frontend log: $FRONTEND_OUT"
  exit 1
fi

url="http://localhost:$FRONTEND_PORT/"
echo "Ready: $url"
echo "Backend PID:  $backend_pid"
echo "Frontend PID: $frontend_pid"

case "$(uname -s)" in
  Darwin) open "$url" >/dev/null 2>&1 || true ;;
  Linux) xdg-open "$url" >/dev/null 2>&1 || true ;;
esac
