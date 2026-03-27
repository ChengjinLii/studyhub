#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DEV_ROOT="${STUDYHUB_LOCAL_DEV_ROOT_DIR:-$ROOT_DIR/.local-dev}"
RUN_DIR="$LOCAL_DEV_ROOT/run"
LOG_DIR="$LOCAL_DEV_ROOT/logs"
BACKEND_PORT="${LOCAL_DEV_BACKEND_PORT:-8011}"
FRONTEND_PORT="${LOCAL_DEV_FRONTEND_PORT:-3000}"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"

mkdir -p "$RUN_DIR" "$LOG_DIR" "$LOCAL_DEV_ROOT"

is_running() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
    return
  fi
  return 1
}

launch_background() {
  local log_file="$1"
  shift
  if command -v setsid >/dev/null 2>&1; then
    setsid "$@" </dev/null >>"$log_file" 2>&1 &
  else
    nohup "$@" >>"$log_file" 2>&1 </dev/null &
  fi
  echo $!
}

if [[ ! -x "$ROOT_DIR/.venv/bin/uvicorn" ]]; then
  echo "missing uvicorn: $ROOT_DIR/.venv/bin/uvicorn"
  exit 1
fi

if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  echo "missing frontend dependencies: cd $ROOT_DIR/frontend && npm install"
  exit 1
fi

if ! is_running "$BACKEND_PID_FILE"; then
  (
    cd "$ROOT_DIR/backend"
    if [[ -f .env ]]; then
      set -a
      # shellcheck disable=SC1091
      source .env
      set +a
    fi
    export STUDYHUB_ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-local-dev}"
    export STUDYHUB_LOCAL_DEV_ROOT_DIR="$LOCAL_DEV_ROOT"
    launch_background "$LOG_DIR/backend.log" "$ROOT_DIR/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" >"$BACKEND_PID_FILE"
  )
fi

if ! is_running "$FRONTEND_PID_FILE"; then
  (
    cd "$ROOT_DIR/frontend"
    export NEXT_PUBLIC_API_BASE="${NEXT_PUBLIC_API_BASE:-http://127.0.0.1:$BACKEND_PORT/api}"
    export API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:$BACKEND_PORT/api}"
    export API_BASE_INTERNAL="${API_BASE_INTERNAL:-http://127.0.0.1:$BACKEND_PORT/api}"
    launch_background "$LOG_DIR/frontend.log" npm run dev -- --hostname 127.0.0.1 --port "$FRONTEND_PORT" >"$FRONTEND_PID_FILE"
  )
fi

echo "local-dev started"
echo "backend:  http://127.0.0.1:$BACKEND_PORT"
echo "frontend: http://127.0.0.1:$FRONTEND_PORT"
echo "logs:     $LOG_DIR"
