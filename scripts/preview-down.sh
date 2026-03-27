#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
RUNTIME_ROOT="${STUDYHUB_PREVIEW_RUNTIME_DIR:-$PRIVATE_DIR/.runtime-preview}"
RUN_DIR="$RUNTIME_ROOT/run"

stop_pid_file() {
  local pid_file="$1"
  local label="$2"
  if [[ ! -f "$pid_file" ]]; then
    echo "$label: not running"
    return 0
  fi
  local pid
  pid="$(cat "$pid_file")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
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
    echo "$label: stopped"
  else
    echo "$label: stale pid file removed"
  fi
  rm -f "$pid_file"
}

stop_pid_file "$RUN_DIR/backend.pid" "preview-backend"
stop_pid_file "$RUN_DIR/frontend.pid" "preview-frontend"
