#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENV_FILE="${PRIVATE_DIR}/.env.production"
RUNTIME_ROOT="${STUDYHUB_PRODUCTION_RUNTIME_DIR:-$PRIVATE_DIR/.runtime-production}"
RUN_DIR="$RUNTIME_ROOT/run"
LOG_DIR="$RUNTIME_ROOT/logs"
BACKEND_PORT="${PRODUCTION_BACKEND_PORT:-8311}"
FRONTEND_PORT="${PRODUCTION_FRONTEND_PORT:-3300}"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
RUN_PREFLIGHT="${STUDYHUB_PRODUCTION_UP_PREFLIGHT:-1}"
REBUILD_FRONTEND="${STUDYHUB_PRODUCTION_REBUILD_FRONTEND:-auto}"

require_tcp_port() {
  local name="$1"
  local value="$2"
  if ! [[ "$value" =~ ^[1-9][0-9]*$ ]] || (( value > 65535 )); then
    echo "$name must be a TCP port between 1 and 65535; got $value"
    exit 2
  fi
}

require_tcp_port "PRODUCTION_BACKEND_PORT" "$BACKEND_PORT"
require_tcp_port "PRODUCTION_FRONTEND_PORT" "$FRONTEND_PORT"

case "$RUN_PREFLIGHT" in
  0|1|false|true)
    ;;
  *)
    echo "STUDYHUB_PRODUCTION_UP_PREFLIGHT must be one of: 1, true, 0, false; got $RUN_PREFLIGHT"
    exit 2
    ;;
esac
case "$REBUILD_FRONTEND" in
  auto|0|1|false|true)
    ;;
  *)
    echo "STUDYHUB_PRODUCTION_REBUILD_FRONTEND must be one of: auto, 1, true, 0, false; got $REBUILD_FRONTEND"
    exit 2
    ;;
esac

mkdir -p "$RUN_DIR" "$LOG_DIR" "$RUNTIME_ROOT"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing production env file: $ENV_FILE"
  exit 1
fi

is_running() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if ! [[ "$pid" =~ ^[1-9][0-9]*$ ]]; then
      return 1
    fi
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

if [[ "$RUN_PREFLIGHT" == "0" || "$RUN_PREFLIGHT" == "false" ]]; then
  echo "production preflight skipped: STUDYHUB_PRODUCTION_UP_PREFLIGHT=$RUN_PREFLIGHT"
else
  STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR" bash "$ROOT_DIR/scripts/runtime/production-preflight.sh"
fi

(
  cd "$ROOT_DIR/frontend"
  if [[ "$REBUILD_FRONTEND" == "1" || "$REBUILD_FRONTEND" == "true" ]]; then
    NEXT_PUBLIC_API_BASE="${NEXT_PUBLIC_API_BASE:-/api}" npm run build >/dev/null
  elif [[ "$REBUILD_FRONTEND" == "0" || "$REBUILD_FRONTEND" == "false" ]]; then
    echo "frontend build skipped: STUDYHUB_PRODUCTION_REBUILD_FRONTEND=$REBUILD_FRONTEND"
  elif is_running "$FRONTEND_PID_FILE" && [[ -f "$ROOT_DIR/frontend/.next/BUILD_ID" ]]; then
    echo "frontend build skipped: running frontend is using the active .next build"
  else
    NEXT_PUBLIC_API_BASE="${NEXT_PUBLIC_API_BASE:-/api}" npm run build >/dev/null
  fi
)

if ! is_running "$BACKEND_PID_FILE"; then
  (
    cd "$ROOT_DIR/backend"
    export STUDYHUB_ENVIRONMENT=production
    export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
    launch_background "$LOG_DIR/backend.log" "$ROOT_DIR/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" >"$BACKEND_PID_FILE"
  )
fi

if ! is_running "$FRONTEND_PID_FILE"; then
  (
    cd "$ROOT_DIR/frontend"
    export NEXT_PUBLIC_API_BASE="${NEXT_PUBLIC_API_BASE:-/api}"
    export API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:$BACKEND_PORT/api}"
    export API_BASE_INTERNAL="${API_BASE_INTERNAL:-http://127.0.0.1:$BACKEND_PORT/api}"
    launch_background "$LOG_DIR/frontend.log" npm run start -- --hostname 127.0.0.1 --port "$FRONTEND_PORT" >"$FRONTEND_PID_FILE"
  )
fi

echo "production started"
echo "backend:  http://127.0.0.1:$BACKEND_PORT"
echo "frontend: http://127.0.0.1:$FRONTEND_PORT"
echo "logs:     $LOG_DIR"
