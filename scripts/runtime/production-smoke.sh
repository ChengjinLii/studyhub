#!/usr/bin/env bash
set -euo pipefail

BACKEND_BASE="${1:-http://127.0.0.1:8311}"
FRONTEND_BASE="${2:-http://127.0.0.1:3300}"

echo "[1/5] backend healthz"
curl --fail --silent --show-error "${BACKEND_BASE%/}/api/healthz" >/dev/null

echo "[2/5] backend readyz"
curl --fail --silent --show-error "${BACKEND_BASE%/}/api/readyz" >/dev/null

echo "[3/5] backend metrics"
curl --fail --silent --show-error "${BACKEND_BASE%/}/api/metrics" | grep -q "studyhub_app_info"

echo "[4/5] readonly materials"
curl --fail --silent --show-error "${BACKEND_BASE%/}/api/materials?page=1&pageSize=1" >/dev/null

echo "[5/5] frontend root"
curl --fail --silent --show-error "${FRONTEND_BASE%/}/" >/dev/null

echo "production smoke passed"
