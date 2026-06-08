#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-production}"
BACKEND_BASE="${STUDYHUB_BACKEND_BASE_URL:-http://127.0.0.1:8311}"
RUN_WORKER_ONCE="${STUDYHUB_P0_RUN_WORKER_ONCE:-0}"
CURL_CONNECT_TIMEOUT="${STUDYHUB_CURL_CONNECT_TIMEOUT:-5}"
CURL_MAX_TIME="${STUDYHUB_CURL_MAX_TIME:-20}"

require_positive_duration() {
  local name="$1"
  local value="$2"
  if ! [[ "$value" =~ ^([0-9]+([.][0-9]+)?|[.][0-9]+)$ ]] || [[ "$value" =~ ^0*([.]0*)?$ ]]; then
    echo "$name must be a positive number of seconds; got $value"
    exit 2
  fi
}

require_positive_duration "STUDYHUB_CURL_CONNECT_TIMEOUT" "$CURL_CONNECT_TIMEOUT"
require_positive_duration "STUDYHUB_CURL_MAX_TIME" "$CURL_MAX_TIME"
CURL_ARGS=(--fail --silent --show-error --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME")

if [[ "$ENVIRONMENT" == "preview" && ! -f "$PRIVATE_DIR/.env.preview" ]]; then
  echo "missing preview env file: $PRIVATE_DIR/.env.preview"
  exit 1
fi

if [[ "$ENVIRONMENT" == "production" && ! -f "$PRIVATE_DIR/.env.production" ]]; then
  echo "missing production env file: $PRIVATE_DIR/.env.production"
  exit 1
fi

echo "[1/7] verify P0 schema columns"
STUDYHUB_ENVIRONMENT="$ENVIRONMENT" \
STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR" \
bash "$ROOT_DIR/scripts/db/db-verify-p0-schema.sh"

echo "[2/7] backend healthz"
curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/healthz" >/dev/null

echo "[3/7] backend readyz"
curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/readyz" >/dev/null

echo "[4/7] backend metrics"
curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/metrics" | grep -q "studyhub_app_info"

echo "[5/7] key readonly APIs"
curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/materials?page=1&pageSize=3" >/dev/null
curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/requests?sort=hot&limit=3" >/dev/null

echo "[6/7] recent schema drift logs"
STUDYHUB_BACKEND_SERVICE="${STUDYHUB_BACKEND_SERVICE:-studyhub-backend.service}" \
STUDYHUB_P0_LOG_SINCE="${STUDYHUB_P0_LOG_SINCE:-30 minutes ago}" \
bash "$ROOT_DIR/scripts/db/db-log-p0-schema.sh"

echo "[7/7] worker once"
if [[ "$RUN_WORKER_ONCE" == "1" || "$RUN_WORKER_ONCE" == "true" ]]; then
  cd "$ROOT_DIR/backend"
  export STUDYHUB_ENVIRONMENT="$ENVIRONMENT"
  export STUDYHUB_PRIVATE_DIR_PATH="$PRIVATE_DIR"
  "$ROOT_DIR/.venv/bin/python" -m app.workers.runner --job all --once
else
  echo "skipped: set STUDYHUB_P0_RUN_WORKER_ONCE=1 to run worker once"
fi

echo "P0 schema smoke passed"
