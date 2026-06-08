#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-preview}"
TARGET_REVISION="${1:-head}"
PRODUCTION_CONFIRM="${YES_PRODUCTION_ALEMBIC_MIGRATION:-}"

if [[ "$ENVIRONMENT" == "preview" && ! -f "$PRIVATE_DIR/.env.preview" ]]; then
  echo "missing preview env file: $PRIVATE_DIR/.env.preview"
  exit 1
fi

if [[ "$ENVIRONMENT" == "production" && ! -f "$PRIVATE_DIR/.env.production" ]]; then
  echo "missing production env file: $PRIVATE_DIR/.env.production"
  exit 1
fi

if [[ "$ENVIRONMENT" == "production" && "$PRODUCTION_CONFIRM" != "I_UNDERSTAND_ALEMBIC_PRODUCTION" ]]; then
  echo "production Alembic migration is disabled by default."
  echo "For P0 additive schema repair, use scripts/db/db-prepare-p0-schema.sh and scripts/db/db-apply-p0-schema.sh."
  echo "To intentionally run Alembic in production, set YES_PRODUCTION_ALEMBIC_MIGRATION=I_UNDERSTAND_ALEMBIC_PRODUCTION."
  exit 2
fi

if [[ ! -x "$ROOT_DIR/.venv/bin/alembic" ]]; then
  echo "missing alembic: install backend dev dependencies with cd backend && ../.venv/bin/pip install -e '.[dev]'"
  exit 1
fi

cd "$ROOT_DIR/backend"
export STUDYHUB_ENVIRONMENT="$ENVIRONMENT"
export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
"$ROOT_DIR/.venv/bin/alembic" upgrade "$TARGET_REVISION"
