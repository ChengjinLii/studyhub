#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-preview}"
OUTPUT_PATH="${1:-}"

if [[ -n "$OUTPUT_PATH" && -z "${OUTPUT_PATH//[[:space:]]/}" ]]; then
  echo "backup output path must not be whitespace only"
  exit 2
fi

if [[ -n "$OUTPUT_PATH" && "$OUTPUT_PATH" != /* ]]; then
  OUTPUT_PATH="$ROOT_DIR/$OUTPUT_PATH"
fi

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
if [[ -n "$OUTPUT_PATH" ]]; then
  "$ROOT_DIR/.venv/bin/python" -m app.ops.db_admin backup --output "$OUTPUT_PATH"
else
  "$ROOT_DIR/.venv/bin/python" -m app.ops.db_admin backup
fi
