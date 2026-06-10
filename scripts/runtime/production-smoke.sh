#!/usr/bin/env bash
set -euo pipefail

BACKEND_BASE="${1:-http://127.0.0.1:8311}"
FRONTEND_BASE="${2:-http://127.0.0.1:3300}"
CURL_CONNECT_TIMEOUT="${STUDYHUB_CURL_CONNECT_TIMEOUT:-5}"
CURL_MAX_TIME="${STUDYHUB_CURL_MAX_TIME:-20}"
PUBLIC_SMOKE_BASES="${STUDYHUB_PUBLIC_SMOKE_BASES:-}"
EXPECTED_GIT_SHA="${STUDYHUB_SMOKE_EXPECTED_GIT_SHA:-}"
PYTHON_BIN="${STUDYHUB_PYTHON_BIN:-python3}"

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

extract_health_git_sha() {
  "$PYTHON_BIN" -c 'import json, sys; payload=json.load(sys.stdin); print(((payload.get("data") or {}).get("build") or {}).get("gitSha") or "")'
}

check_health_git_sha() {
  local label="$1"
  local health_url="$2"
  local response
  response="$(curl "${CURL_ARGS[@]}" "$health_url")"
  if [[ -n "$EXPECTED_GIT_SHA" ]]; then
    local actual_sha
    actual_sha="$(printf '%s' "$response" | extract_health_git_sha)"
    if [[ "$actual_sha" != "$EXPECTED_GIT_SHA" ]]; then
      echo "$label gitSha mismatch: expected $EXPECTED_GIT_SHA, got ${actual_sha:-<empty>}"
      exit 1
    fi
  fi
}

echo "[1/5] backend healthz"
check_health_git_sha "backend healthz" "${BACKEND_BASE%/}/api/healthz"

echo "[2/5] backend readyz"
curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/readyz" >/dev/null

echo "[3/5] backend metrics"
curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/metrics" | grep -q "studyhub_app_info"

echo "[4/5] readonly materials"
curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/materials?page=1&pageSize=1" >/dev/null

echo "[5/5] frontend root"
curl "${CURL_ARGS[@]}" "${FRONTEND_BASE%/}/" >/dev/null

if [[ -n "$PUBLIC_SMOKE_BASES" ]]; then
  echo "[public] configured public entrypoints"
  for public_base in $PUBLIC_SMOKE_BASES; do
    public_base="${public_base%/}"
    if [[ -z "$public_base" ]]; then
      continue
    fi
    echo "[public] $public_base healthz"
    check_health_git_sha "$public_base healthz" "$public_base/api/healthz"
    echo "[public] $public_base frontend root"
    curl "${CURL_ARGS[@]}" "$public_base/" >/dev/null
  done
fi

echo "production smoke passed"
