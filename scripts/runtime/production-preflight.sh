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

if [[ -n "$SCHEMA_CHECK_COLUMNS" && -z "${SCHEMA_CHECK_COLUMNS//[[:space:]]/}" ]]; then
  echo "STUDYHUB_PRODUCTION_SCHEMA_CHECK_COLUMNS must be empty for a full schema check or contain table.column values; got whitespace only"
  exit 2
fi

SCHEMA_CHECK_COLUMN_ITEMS=()
if [[ -n "$SCHEMA_CHECK_COLUMNS" ]]; then
  read -r -a SCHEMA_CHECK_COLUMN_ITEMS <<< "$SCHEMA_CHECK_COLUMNS"
  for column in "${SCHEMA_CHECK_COLUMN_ITEMS[@]}"; do
    if ! [[ "$column" =~ ^[A-Za-z_][A-Za-z0-9_]*[.][A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "STUDYHUB_PRODUCTION_SCHEMA_CHECK_COLUMNS entries must use table.column identifiers; got $column"
      exit 2
    fi
  done
fi

cd "$ROOT_DIR/backend"
export STUDYHUB_ENVIRONMENT=production
export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
"$ROOT_DIR/.venv/bin/python" -m app.ops.preflight --network --timeout-seconds "$PREFLIGHT_TIMEOUT_SECONDS"
schema_check_command=("$ROOT_DIR/.venv/bin/python" -m app.ops.db_admin check-schema)
if [[ "${#SCHEMA_CHECK_COLUMN_ITEMS[@]}" -gt 0 ]]; then
  for column in "${SCHEMA_CHECK_COLUMN_ITEMS[@]}"; do
    schema_check_command+=(--only "$column")
  done
fi
"${schema_check_command[@]}"
