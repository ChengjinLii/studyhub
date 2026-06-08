#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-preview}"
PRODUCTION_CONFIRM="${YES_PRODUCTION_ALEMBIC_STAMP:-}"

if [[ "$ENVIRONMENT" == "preview" && ! -f "$PRIVATE_DIR/.env.preview" ]]; then
  echo "missing preview env file: $PRIVATE_DIR/.env.preview"
  exit 1
fi

if [[ "$ENVIRONMENT" == "production" && ! -f "$PRIVATE_DIR/.env.production" ]]; then
  echo "missing production env file: $PRIVATE_DIR/.env.production"
  exit 1
fi

if [[ "$ENVIRONMENT" == "production" && "$PRODUCTION_CONFIRM" != "I_UNDERSTAND_STAMP_PRODUCTION" ]]; then
  echo "production Alembic stamp is disabled by default."
  echo "Run scripts/db/db-verify-p0-schema.sh first; only stamp production after confirming schema state manually."
  echo "To intentionally stamp production, set YES_PRODUCTION_ALEMBIC_STAMP=I_UNDERSTAND_STAMP_PRODUCTION."
  exit 2
fi

if [[ ! -x "$ROOT_DIR/.venv/bin/alembic" ]]; then
  echo "missing alembic: install backend dev dependencies with cd backend && ../.venv/bin/pip install -e '.[dev]'"
  exit 1
fi

cd "$ROOT_DIR/backend"
export STUDYHUB_ENVIRONMENT="$ENVIRONMENT"
export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
"$ROOT_DIR/.venv/bin/alembic" stamp head
