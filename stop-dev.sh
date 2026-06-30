#!/usr/bin/env bash
set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8002}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT/.dev-pids.json"

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

if [ -f "$PID_FILE" ]; then
  "$PYTHON_BIN" - <<PY
import json
import os
import signal
from pathlib import Path

path = Path(r"$PID_FILE")
data = json.loads(path.read_text(encoding="utf-8"))
for key in ("backend", "frontend"):
    pid = data.get(key)
    if pid:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
path.unlink(missing_ok=True)
PY
fi

stop_port "$BACKEND_PORT"
stop_port "$FRONTEND_PORT"
echo "Stopped CS Gap Assist dev server."
