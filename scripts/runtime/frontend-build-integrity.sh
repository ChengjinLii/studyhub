#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
FRONTEND_BASE="${STUDYHUB_FRONTEND_BASE:-http://127.0.0.1:3300}"

required_files=(
  "$FRONTEND_DIR/.next/BUILD_ID"
  "$FRONTEND_DIR/.next/server/pages/index.js"
  "$FRONTEND_DIR/.next/server/pages/404.html"
  "$FRONTEND_DIR/.next/server/pages/materials/[id].js"
  "$FRONTEND_DIR/.next/server/pages/pay/[id].js"
)

for file in "${required_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "missing frontend build artifact: $file"
    exit 1
  fi
done

curl_status() {
  local path="$1"
  curl -sS -L -o /dev/null -w '%{http_code}' \
    --connect-timeout "${STUDYHUB_CURL_CONNECT_TIMEOUT:-5}" \
    --max-time "${STUDYHUB_CURL_MAX_TIME:-20}" \
    "${FRONTEND_BASE%/}$path"
}

home_status="$(curl_status "/")"
if [[ "$home_status" != "200" ]]; then
  echo "frontend home smoke failed: HTTP $home_status"
  exit 1
fi

not_found_status="$(curl_status "/__studyhub_missing_page_smoke__")"
if [[ "$not_found_status" != "404" ]]; then
  echo "frontend 404 smoke failed: HTTP $not_found_status"
  exit 1
fi

echo "Frontend build integrity check passed."
