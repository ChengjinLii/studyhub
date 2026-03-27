#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-preview}"
RUNTIME_ROOT="${STUDYHUB_WORKER_RUNTIME_DIR:-$PRIVATE_DIR/.runtime-${ENVIRONMENT}}"
PID_FILE="$RUNTIME_ROOT/run/worker.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "worker: not running"
  exit 0
fi

pid="$(cat "$PID_FILE")"
if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
  kill "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 0.2
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  echo "worker: stopped"
else
  echo "worker: stale pid file removed"
fi
rm -f "$PID_FILE"
