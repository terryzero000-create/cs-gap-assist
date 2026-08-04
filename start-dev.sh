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
missing = [m for m in ["fastapi", "uvicorn", "pydantic_settings", "numpy", "httpx", "fitz"] if importlib.util.find_spec(m) is None]
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

api_key="$("$PYTHON_BIN" - "$ROOT/.env" "$ROOT/.env.example" <<'PY'
import re
import secrets
import shutil
import sys
from pathlib import Path

env_path = Path(sys.argv[1])
if not env_path.exists():
    shutil.copyfile(sys.argv[2], env_path)
content = env_path.read_text(encoding="utf-8-sig")
match = re.search(r"^APP_API_KEY=(.*)$", content, flags=re.MULTILINE)
value = match.group(1).strip() if match else ""
if not value or value == "replace-with-a-long-local-token":
    value = secrets.token_urlsafe(32)
    if match:
        content = re.sub(r"^APP_API_KEY=.*$", f"APP_API_KEY={value}", content, count=1, flags=re.MULTILINE)
    else:
        content = f"{content.rstrip()}\nAPP_API_KEY={value}\n"
    env_path.write_text(content, encoding="utf-8")
print(value)
PY
)"
export APP_API_KEY="$api_key"

echo "Releasing ports $BACKEND_PORT and $FRONTEND_PORT..."
stop_port "$BACKEND_PORT"
stop_port "$FRONTEND_PORT"
sleep 2

rm -f "$BACKEND_OUT" "$BACKEND_ERR" "$FRONTEND_OUT" "$FRONTEND_ERR"

echo "Starting backend on 127.0.0.1:$BACKEND_PORT..."
"$PYTHON_BIN" -m uvicorn backend.main:app --host 127.0.0.1 --port "$BACKEND_PORT" >"$BACKEND_OUT" 2>"$BACKEND_ERR" &
backend_pid=$!

if ! wait_url "http://127.0.0.1:$BACKEND_PORT/health/live"; then
  echo "Backend did not become healthy in time."
  echo "Backend log:  $BACKEND_ERR"
  exit 1
fi

echo "Starting frontend on 127.0.0.1:$FRONTEND_PORT..."
npm run dev --prefix "$FRONTEND_DIR" -- --host 127.0.0.1 --port "$FRONTEND_PORT" >"$FRONTEND_OUT" 2>"$FRONTEND_ERR" &
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

if ! wait_url "http://127.0.0.1:$FRONTEND_PORT/api/v1/health/live"; then
  echo "Startup did not become healthy in time."
  echo "Backend log:  $BACKEND_ERR"
  echo "Frontend log: $FRONTEND_OUT"
  exit 1
fi

url="http://localhost:$FRONTEND_PORT/"
echo "Ready: $url"
echo "Backend PID:  $backend_pid"
echo "Frontend PID: $frontend_pid"
echo "Local API authentication is configured automatically."

case "$(uname -s)" in
  Darwin) open "$url" >/dev/null 2>&1 || true ;;
  Linux) xdg-open "$url" >/dev/null 2>&1 || true ;;
esac
