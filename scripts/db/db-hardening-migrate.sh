#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMMAND="${1:-plan}"
MODULE="${2:-}"
if [[ "$COMMAND" != plan && "$COMMAND" != apply ]]; then
  echo "usage: $0 {plan|apply} {finance-outbox|material-security|auth-session}"
  exit 2
fi
if [[ -z "$MODULE" ]]; then
  echo "migration module is required"
  exit 2
fi
args=("$COMMAND" "$MODULE")
if [[ "$COMMAND" == apply ]]; then
  if [[ -z "${STUDYHUB_HARDENING_PLAN_TOKEN:-}" ]]; then
    echo "STUDYHUB_HARDENING_PLAN_TOKEN is required"
    exit 2
  fi
  args+=(--plan-token "$STUDYHUB_HARDENING_PLAN_TOKEN")
fi
cd "$ROOT_DIR/backend"
export STUDYHUB_ENVIRONMENT=production
export STUDYHUB_PRIVATE_DIR_PATH="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
exec "$ROOT_DIR/.venv/bin/python" -m app.ops.hardening_migrate "${args[@]}"
