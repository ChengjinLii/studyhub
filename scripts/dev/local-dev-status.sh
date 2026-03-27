#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCAL_DEV_ROOT="${STUDYHUB_LOCAL_DEV_ROOT_DIR:-$ROOT_DIR/.local-dev}"
RUN_DIR="$LOCAL_DEV_ROOT/run"
BACKEND_PORT="${LOCAL_DEV_BACKEND_PORT:-8011}"
FRONTEND_PORT="${LOCAL_DEV_FRONTEND_PORT:-3000}"

print_pid_status() {
  local pid_file="$1"
  local label="$2"
  if [[ ! -f "$pid_file" ]]; then
    echo "$label: down"
    return 0
  fi
  local pid
  pid="$(cat "$pid_file")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "$label: up (pid=$pid)"
  else
    echo "$label: stale pid file"
  fi
}

print_pid_status "$RUN_DIR/backend.pid" "backend"
print_pid_status "$RUN_DIR/frontend.pid" "frontend"

echo
echo "backend health:"
curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/healthz" || echo "unreachable"

echo
echo
echo "frontend probe:"
curl -I -fsS "http://127.0.0.1:$FRONTEND_PORT" | head -n 1 || echo "unreachable"
