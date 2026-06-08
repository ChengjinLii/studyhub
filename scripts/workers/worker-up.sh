#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-preview}"
RUNTIME_ROOT="${STUDYHUB_WORKER_RUNTIME_DIR:-$PRIVATE_DIR/.runtime-${ENVIRONMENT}}"
RUN_DIR="$RUNTIME_ROOT/run"
LOG_DIR="$RUNTIME_ROOT/logs"
PID_FILE="$RUN_DIR/worker.pid"
JOB_NAME="${WORKER_JOB:-all}"
INTERVAL_SECONDS="${WORKER_INTERVAL_SECONDS:-60}"
RUN_SCHEMA_PREFLIGHT="${STUDYHUB_WORKER_SCHEMA_PREFLIGHT:-1}"

if ! [[ "$INTERVAL_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "WORKER_INTERVAL_SECONDS must be a positive integer; got $INTERVAL_SECONDS"
  exit 2
fi

case "$RUN_SCHEMA_PREFLIGHT" in
  0|1|false|true)
    ;;
  *)
    echo "STUDYHUB_WORKER_SCHEMA_PREFLIGHT must be one of: 1, true, 0, false; got $RUN_SCHEMA_PREFLIGHT"
    exit 2
    ;;
esac

mkdir -p "$RUN_DIR" "$LOG_DIR"

if [[ "$ENVIRONMENT" == "production" && ! -f "$PRIVATE_DIR/.env.production" ]]; then
  echo "missing production env file: $PRIVATE_DIR/.env.production"
  exit 1
fi

if [[ "$ENVIRONMENT" == "preview" && ! -f "$PRIVATE_DIR/.env.preview" ]]; then
  echo "missing preview env file: $PRIVATE_DIR/.env.preview"
  exit 1
fi

if [[ "$ENVIRONMENT" == "production" ]]; then
  if [[ "$RUN_SCHEMA_PREFLIGHT" == "0" || "$RUN_SCHEMA_PREFLIGHT" == "false" ]]; then
    echo "worker schema preflight skipped: STUDYHUB_WORKER_SCHEMA_PREFLIGHT=$RUN_SCHEMA_PREFLIGHT"
  else
    STUDYHUB_ENVIRONMENT="$ENVIRONMENT" \
    STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR" \
    bash "$ROOT_DIR/scripts/db/db-verify-p0-schema.sh"
  fi
fi

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "worker already running (pid=$pid)"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if command -v setsid >/dev/null 2>&1; then
  setsid bash -lc "
    cd '$ROOT_DIR/backend'
    export STUDYHUB_ENVIRONMENT='$ENVIRONMENT'
    export STUDYHUB_PRIVATE_DIR_PATH='$PRIVATE_DIR'
    while true; do
      '$ROOT_DIR/.venv/bin/python' -m app.workers.runner --job '$JOB_NAME'
      sleep '$INTERVAL_SECONDS'
    done
  " </dev/null >>"$LOG_DIR/worker.log" 2>&1 &
else
  nohup bash -lc "
    cd '$ROOT_DIR/backend'
    export STUDYHUB_ENVIRONMENT='$ENVIRONMENT'
    export STUDYHUB_PRIVATE_DIR_PATH='$PRIVATE_DIR'
    while true; do
      '$ROOT_DIR/.venv/bin/python' -m app.workers.runner --job '$JOB_NAME'
      sleep '$INTERVAL_SECONDS'
    done
  " >>"$LOG_DIR/worker.log" 2>&1 </dev/null &
fi
echo $! >"$PID_FILE"

echo "worker started"
echo "env:      $ENVIRONMENT"
echo "job:      $JOB_NAME"
echo "interval: ${INTERVAL_SECONDS}s"
echo "logs:     $LOG_DIR/worker.log"
