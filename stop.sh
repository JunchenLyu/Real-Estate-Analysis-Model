#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="$PROJECT_DIR/.runtime"

stop_process() {
  local name="$1"
  local pid_file="$RUNTIME_DIR/$2.pid"
  if [ ! -f "$pid_file" ]; then
    return
  fi

  local pid
  pid="$(tr -cd '0-9' < "$pid_file")"
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    echo "[ok] Stopped $name (PID $pid)."
  fi
  rm -f "$pid_file"
}

stop_process "backend" "backend"
stop_process "frontend" "frontend"
