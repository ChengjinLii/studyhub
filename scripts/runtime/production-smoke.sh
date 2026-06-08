#!/usr/bin/env bash
set -euo pipefail

BACKEND_BASE="${1:-http://127.0.0.1:8311}"
FRONTEND_BASE="${2:-http://127.0.0.1:3300}"
CURL_CONNECT_TIMEOUT="${STUDYHUB_CURL_CONNECT_TIMEOUT:-5}"
CURL_MAX_TIME="${STUDYHUB_CURL_MAX_TIME:-20}"
CURL_ARGS=(--fail --silent --show-error --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME")

echo "[1/5] backend healthz"
curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/healthz" >/dev/null

echo "[2/5] backend readyz"
curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/readyz" >/dev/null

echo "[3/5] backend metrics"
curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/metrics" | grep -q "studyhub_app_info"

echo "[4/5] readonly materials"
curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/materials?page=1&pageSize=1" >/dev/null

echo "[5/5] frontend root"
curl "${CURL_ARGS[@]}" "${FRONTEND_BASE%/}/" >/dev/null

echo "production smoke passed"
