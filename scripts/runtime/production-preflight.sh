#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
PREFLIGHT_TIMEOUT_SECONDS="${STUDYHUB_PREFLIGHT_TIMEOUT_SECONDS:-5}"
SCHEMA_BASELINE="${STUDYHUB_PRODUCTION_SCHEMA_BASELINE:-$ROOT_DIR/deploy/schema/production-legacy-baseline.json}"

if [[ ! -f "$PRIVATE_DIR/.env.production" ]]; then
  echo "missing production env file: $PRIVATE_DIR/.env.production"
  exit 1
fi

if [[ ! -f "$SCHEMA_BASELINE" ]]; then
  echo "missing reviewed production schema baseline: $SCHEMA_BASELINE"
  exit 1
fi

cd "$ROOT_DIR/backend"
export STUDYHUB_ENVIRONMENT=production
export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
"$ROOT_DIR/.venv/bin/python" -m app.ops.preflight --network --timeout-seconds "$PREFLIGHT_TIMEOUT_SECONDS"
"$ROOT_DIR/.venv/bin/python" -m app.ops.db_admin check
"$ROOT_DIR/.venv/bin/python" -m app.ops.schema_baseline --baseline "$SCHEMA_BASELINE"
