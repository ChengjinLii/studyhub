#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-production}"
BACKEND_BASE="${STUDYHUB_BACKEND_BASE_URL:-http://127.0.0.1:8311}"
RUN_WORKER_ONCE="${STUDYHUB_P0_RUN_WORKER_ONCE:-0}"

if [[ "$ENVIRONMENT" == "preview" && ! -f "$PRIVATE_DIR/.env.preview" ]]; then
  echo "missing preview env file: $PRIVATE_DIR/.env.preview"
  exit 1
fi

if [[ "$ENVIRONMENT" == "production" && ! -f "$PRIVATE_DIR/.env.production" ]]; then
  echo "missing production env file: $PRIVATE_DIR/.env.production"
  exit 1
fi

echo "[1/6] verify P0 schema columns"
STUDYHUB_ENVIRONMENT="$ENVIRONMENT" \
STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR" \
bash "$ROOT_DIR/scripts/db/db-verify-p0-schema.sh"

echo "[2/6] backend healthz"
curl --fail --silent --show-error "${BACKEND_BASE%/}/api/healthz" >/dev/null

echo "[3/6] backend readyz"
curl --fail --silent --show-error "${BACKEND_BASE%/}/api/readyz" >/dev/null

echo "[4/6] backend metrics"
curl --fail --silent --show-error "${BACKEND_BASE%/}/api/metrics" | grep -q "studyhub_app_info"

echo "[5/6] key readonly APIs"
curl --fail --silent --show-error "${BACKEND_BASE%/}/api/materials?page=1&pageSize=3" >/dev/null
curl --fail --silent --show-error "${BACKEND_BASE%/}/api/requests?sort=hot&limit=3" >/dev/null

echo "[6/6] worker once"
if [[ "$RUN_WORKER_ONCE" == "1" || "$RUN_WORKER_ONCE" == "true" ]]; then
  cd "$ROOT_DIR/backend"
  export STUDYHUB_ENVIRONMENT="$ENVIRONMENT"
  export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
  "$ROOT_DIR/.venv/bin/python" -m app.workers.runner --job all --once
else
  echo "skipped: set STUDYHUB_P0_RUN_WORKER_ONCE=1 to run worker once"
fi

echo "P0 schema smoke passed"
