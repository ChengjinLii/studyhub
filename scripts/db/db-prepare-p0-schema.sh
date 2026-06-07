#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-production}"

if [[ "$ENVIRONMENT" != "production" ]]; then
  echo "db-prepare-p0-schema.sh is production-only; got STUDYHUB_ENVIRONMENT=$ENVIRONMENT"
  exit 2
fi

if [[ ! -f "$PRIVATE_DIR/.env.production" ]]; then
  echo "missing production env file: $PRIVATE_DIR/.env.production"
  exit 1
fi

echo "[1/2] backup production database"
STUDYHUB_ENVIRONMENT="$ENVIRONMENT" \
STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR" \
bash "$ROOT_DIR/scripts/db/db-backup.sh"

echo "[2/2] generate P0 additive migration plan"
STUDYHUB_ENVIRONMENT="$ENVIRONMENT" \
STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR" \
bash "$ROOT_DIR/scripts/db/db-plan-p0-schema.sh"

echo "P0 schema preparation complete; review backupFile, SQL, and planToken before applying."
