#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-production}"
SCHEMA_COLUMNS="${STUDYHUB_P0_SCHEMA_COLUMNS:-market_items.source orders.uploader_id}"

if [[ "$ENVIRONMENT" == "preview" && ! -f "$PRIVATE_DIR/.env.preview" ]]; then
  echo "missing preview env file: $PRIVATE_DIR/.env.preview"
  exit 1
fi

if [[ "$ENVIRONMENT" == "production" && ! -f "$PRIVATE_DIR/.env.production" ]]; then
  echo "missing production env file: $PRIVATE_DIR/.env.production"
  exit 1
fi

if [[ -z "$SCHEMA_COLUMNS" ]]; then
  echo "STUDYHUB_P0_SCHEMA_COLUMNS must contain at least one table.column value"
  exit 2
fi

command_args=("$ROOT_DIR/.venv/bin/python" -m app.ops.db_admin check-schema)
for column in $SCHEMA_COLUMNS; do
  command_args+=(--only "$column")
done

cd "$ROOT_DIR/backend"
export STUDYHUB_ENVIRONMENT="$ENVIRONMENT"
export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
"${command_args[@]}"
