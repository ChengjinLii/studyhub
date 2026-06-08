#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
RUNTIME_ROOT="${STUDYHUB_PREVIEW_RUNTIME_DIR:-$PRIVATE_DIR/.runtime-preview}"
RUN_DIR="$RUNTIME_ROOT/run"
BACKEND_PORT="${PREVIEW_BACKEND_PORT:-8211}"
FRONTEND_PORT="${PREVIEW_FRONTEND_PORT:-3200}"

require_tcp_port() {
  local name="$1"
  local value="$2"
  if ! [[ "$value" =~ ^[1-9][0-9]*$ ]] || (( value > 65535 )); then
    echo "$name must be a TCP port between 1 and 65535; got $value"
    exit 2
  fi
}

require_tcp_port "PREVIEW_BACKEND_PORT" "$BACKEND_PORT"
require_tcp_port "PREVIEW_FRONTEND_PORT" "$FRONTEND_PORT"

status_pid_file() {
  local pid_file="$1"
  local label="$2"
  if [[ ! -f "$pid_file" ]]; then
    echo "$label: down"
    return
  fi
  local pid
  pid="$(cat "$pid_file")"
  if ! [[ "$pid" =~ ^[1-9][0-9]*$ ]]; then
    echo "$label: invalid pid file"
    return
  fi
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "$label: up (pid=$pid)"
  else
    echo "$label: stale pid file"
  fi
}

status_pid_file "$RUN_DIR/backend.pid" "preview-backend"
status_pid_file "$RUN_DIR/frontend.pid" "preview-frontend"
echo "backend health: http://127.0.0.1:$BACKEND_PORT/api/healthz"
echo "backend ready:  http://127.0.0.1:$BACKEND_PORT/api/readyz"
echo "backend metrics:http://127.0.0.1:$BACKEND_PORT/api/metrics"
echo "frontend:       http://127.0.0.1:$FRONTEND_PORT"
