#!/usr/bin/env bash
set -euo pipefail

BACKEND_BASE="${1:-http://127.0.0.1:8211}"
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

curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/healthz"
curl "${CURL_ARGS[@]}" "${BACKEND_BASE%/}/api/readyz" >/dev/null
