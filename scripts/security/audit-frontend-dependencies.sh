#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND_DIR="${STUDYHUB_FRONTEND_DIR:-$ROOT_DIR/frontend}"
REGISTRY="${STUDYHUB_NPM_AUDIT_REGISTRY:-https://registry.npmjs.org}"
NETWORK_POLICY="${STUDYHUB_AUDIT_NETWORK_POLICY:-warn}"
ATTEMPTS="${STUDYHUB_NPM_AUDIT_ATTEMPTS:-3}"
LOG_FILE="$(mktemp /tmp/studyhub-npm-audit.XXXXXX)"
trap 'rm -f "$LOG_FILE"' EXIT

if ! [[ "$ATTEMPTS" =~ ^[1-9][0-9]*$ ]]; then
  echo "STUDYHUB_NPM_AUDIT_ATTEMPTS must be a positive integer" >&2
  exit 2
fi
if [[ "$NETWORK_POLICY" != "warn" && "$NETWORK_POLICY" != "fail" ]]; then
  echo "STUDYHUB_AUDIT_NETWORK_POLICY must be warn or fail" >&2
  exit 2
fi

for ((attempt = 1; attempt <= ATTEMPTS; attempt += 1)); do
  if npm --prefix "$FRONTEND_DIR" audit --omit=dev --audit-level=high --registry="$REGISTRY" >"$LOG_FILE" 2>&1; then
    cat "$LOG_FILE"
    exit 0
  else
    status=$?
  fi
  if ! grep -Eqi 'audit endpoint returned an error|ECONNRESET|ECONNREFUSED|ENOTFOUND|ETIMEDOUT|EAI_AGAIN|socket hang up|network.*(error|unavailable)' "$LOG_FILE"; then
    cat "$LOG_FILE" >&2
    exit "$status"
  fi
  cat "$LOG_FILE" >&2
  if (( attempt < ATTEMPTS )); then
    sleep $((attempt * 5))
  fi
done

message="npm audit registry remained unavailable after $ATTEMPTS attempts; no vulnerability result was produced"
if [[ "$NETWORK_POLICY" == "fail" ]]; then
  echo "$message" >&2
  exit 1
fi
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  echo "::warning title=Frontend dependency audit unavailable::$message"
else
  echo "warning: $message" >&2
fi
