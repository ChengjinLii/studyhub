#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-production}"
SCHEMA_COLUMNS="${STUDYHUB_P0_SCHEMA_COLUMNS:-market_items.source orders.uploader_id}"
PLAN_TOKEN="${STUDYHUB_P0_PLAN_TOKEN:-}"
CONFIRM="${YES_PRODUCTION_SCHEMA_ADD_COLUMNS:-}"
BACKUP_MAX_AGE_MINUTES="${STUDYHUB_BACKUP_MAX_AGE_MINUTES:-120}"

if [[ "$ENVIRONMENT" != "production" ]]; then
  echo "db-apply-p0-schema.sh is production-only; got STUDYHUB_ENVIRONMENT=$ENVIRONMENT"
  exit 2
fi

if [[ ! -f "$PRIVATE_DIR/.env.production" ]]; then
  echo "missing production env file: $PRIVATE_DIR/.env.production"
  exit 1
fi

if [[ -z "${SCHEMA_COLUMNS//[[:space:]]/}" ]]; then
  echo "STUDYHUB_P0_SCHEMA_COLUMNS must contain at least one table.column value"
  exit 2
fi

if ! [[ "$BACKUP_MAX_AGE_MINUTES" =~ ^[1-9][0-9]*$ ]]; then
  echo "STUDYHUB_BACKUP_MAX_AGE_MINUTES must be a positive integer; got $BACKUP_MAX_AGE_MINUTES"
  exit 2
fi

if [[ -z "$PLAN_TOKEN" ]]; then
  echo "missing STUDYHUB_P0_PLAN_TOKEN; run scripts/db/db-plan-p0-schema.sh and copy planToken first"
  exit 2
fi

if [[ "$CONFIRM" != "I_UNDERSTAND_ADD_COLUMNS" ]]; then
  echo "set YES_PRODUCTION_SCHEMA_ADD_COLUMNS=I_UNDERSTAND_ADD_COLUMNS to execute additive production DDL"
  exit 2
fi

command_args=(
  "$ROOT_DIR/.venv/bin/python" -m app.ops.db_admin migrate-additive
  --yes
  --backup-max-age-minutes "$BACKUP_MAX_AGE_MINUTES"
  --confirm-plan-token "$PLAN_TOKEN"
)
for column in $SCHEMA_COLUMNS; do
  command_args+=(--only "$column")
done

cd "$ROOT_DIR/backend"
export STUDYHUB_ENVIRONMENT="$ENVIRONMENT"
export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
"${command_args[@]}"
