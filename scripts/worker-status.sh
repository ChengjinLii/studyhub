#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-preview}"
RUNTIME_ROOT="${STUDYHUB_WORKER_RUNTIME_DIR:-$PRIVATE_DIR/.runtime-${ENVIRONMENT}}"
PID_FILE="$RUNTIME_ROOT/run/worker.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "worker: down"
  exit 0
fi

pid="$(cat "$PID_FILE")"
if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
  echo "worker: up (pid=$pid)"
else
  echo "worker: stale pid file"
fi
