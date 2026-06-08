#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
SCHEMA_CHECK_COLUMNS="${STUDYHUB_PRODUCTION_SCHEMA_CHECK_COLUMNS-market_items.source orders.uploader_id}"
PREFLIGHT_TIMEOUT_SECONDS="${STUDYHUB_PREFLIGHT_TIMEOUT_SECONDS:-5}"

if [[ ! -f "$PRIVATE_DIR/.env.production" ]]; then
  echo "missing production env file: $PRIVATE_DIR/.env.production"
  exit 1
fi

cd "$ROOT_DIR/backend"
export STUDYHUB_ENVIRONMENT=production
export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
"$ROOT_DIR/.venv/bin/python" -m app.ops.preflight --network --timeout-seconds "$PREFLIGHT_TIMEOUT_SECONDS"
schema_check_command=("$ROOT_DIR/.venv/bin/python" -m app.ops.db_admin check-schema)
if [[ -n "$SCHEMA_CHECK_COLUMNS" ]]; then
  for column in $SCHEMA_CHECK_COLUMNS; do
    schema_check_command+=(--only "$column")
  done
fi
"${schema_check_command[@]}"
