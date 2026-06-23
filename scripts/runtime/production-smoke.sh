#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PRIVATE_DIR="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
ENV_FILE="$PRIVATE_DIR/.env.production"
BACKEND_BASE="${1:-http://127.0.0.1:8311}"
FRONTEND_BASE="${2:-http://127.0.0.1:3300}"
CURL_CONNECT_TIMEOUT="${STUDYHUB_CURL_CONNECT_TIMEOUT:-5}"
CURL_MAX_TIME="${STUDYHUB_CURL_MAX_TIME:-20}"
PYTHON_BIN="${STUDYHUB_PYTHON_BIN:-python3}"
PUBLIC_SMOKE_BASES_MODE="${STUDYHUB_PUBLIC_SMOKE_BASES-__auto__}"
EXPECTED_GIT_SHA="${STUDYHUB_SMOKE_EXPECTED_GIT_SHA:-$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || true)}"

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

derive_public_smoke_bases() {
  if [[ ! -f "$ENV_FILE" ]]; then
    return
  fi
  "$PYTHON_BIN" - "$ENV_FILE" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

env_file = Path(sys.argv[1])
values: dict[str, str] = {}
for raw_line in env_file.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key.strip()] = value.strip().strip('"').strip("'")

origins: list[str] = []
for item in [values.get("STUDYHUB_PUBLIC_SITE_BASE_URL"), *values.get("STUDYHUB_TRUSTED_SITE_ORIGINS", "").split(",")]:
    candidate = (item or "").strip().rstrip("/")
    if not candidate:
        continue
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        continue
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"}:
        continue
    if all(part.isdigit() for part in host.split(".") if part):
        continue
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in origins:
        origins.append(origin)

print(" ".join(origins))
PY
}

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

if [[ "$PUBLIC_SMOKE_BASES_MODE" == "__auto__" ]]; then
  PUBLIC_SMOKE_BASES="$(derive_public_smoke_bases)"
elif [[ "$PUBLIC_SMOKE_BASES_MODE" == "none" || "$PUBLIC_SMOKE_BASES_MODE" == "off" ]]; then
  PUBLIC_SMOKE_BASES=""
else
  PUBLIC_SMOKE_BASES="$PUBLIC_SMOKE_BASES_MODE"
fi

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
