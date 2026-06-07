#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-preview}"
CHECK_MODE="${STUDYHUB_DB_CHECK_MODE:-schema}"

if [[ "$ENVIRONMENT" == "preview" && ! -f "$PRIVATE_DIR/.env.preview" ]]; then
  echo "missing preview env file: $PRIVATE_DIR/.env.preview"
  exit 1
fi

if [[ "$ENVIRONMENT" == "production" && ! -f "$PRIVATE_DIR/.env.production" ]]; then
  echo "missing production env file: $PRIVATE_DIR/.env.production"
  exit 1
fi

cd "$ROOT_DIR/backend"
export STUDYHUB_ENVIRONMENT="$ENVIRONMENT"
export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
case "$CHECK_MODE" in
  schema)
    "$ROOT_DIR/.venv/bin/python" -m app.ops.db_admin check-schema
    ;;
  tables)
    "$ROOT_DIR/.venv/bin/python" -m app.ops.db_admin check
    ;;
  *)
    echo "unsupported STUDYHUB_DB_CHECK_MODE=$CHECK_MODE; expected schema or tables"
    exit 2
    ;;
esac
