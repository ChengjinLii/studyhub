#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-https://study-hub.cn}"
BASE_URL="${BASE_URL%/}"

if [[ ! "$BASE_URL" =~ ^https?://[^/]+$ ]]; then
  echo "usage: $0 [https://host]" >&2
  exit 2
fi
command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 1; }

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

header_value() {
  local file="$1"
  local name="$2"
  awk -v wanted="${name,,}" '
    {
      line=$0
      sub(/\r$/, "", line)
      split(line, parts, ":")
      key=tolower(parts[1])
      if (key == wanted) {
        sub(/^[^:]+:[[:space:]]*/, "", line)
        print line
      }
    }
  ' "$file"
}

assert_single_header() {
  local file="$1"
  local name="$2"
  local expected="$3"
  local values count
  values="$(header_value "$file" "$name")"
  count="$(printf '%s\n' "$values" | sed '/^$/d' | wc -l | tr -d ' ')"
  if [[ "$count" != "1" ]]; then
    echo "FAIL: $name expected once, found $count in $file" >&2
    return 1
  fi
  if [[ "$values" != *"$expected"* ]]; then
    echo "FAIL: $name does not contain: $expected" >&2
    echo "actual: $values" >&2
    return 1
  fi
}

check_url() {
  local label="$1"
  local path="$2"
  local headers="$tmp_dir/$label.headers"
  local status

  status="$(curl --silent --show-error --location --max-redirs 3 \
    --output /dev/null --dump-header "$headers" --write-out '%{http_code}' \
    "$BASE_URL$path")"
  if [[ "$status" == "000" || "$status" -ge 500 ]]; then
    echo "FAIL: $BASE_URL$path returned HTTP $status" >&2
    return 1
  fi

  assert_single_header "$headers" "X-Content-Type-Options" "nosniff"
  assert_single_header "$headers" "X-Frame-Options" "DENY"
  assert_single_header "$headers" "Referrer-Policy" "strict-origin-when-cross-origin"
  assert_single_header "$headers" "Permissions-Policy" "camera=(), microphone=(), geolocation=()"
  assert_single_header "$headers" "Content-Security-Policy-Report-Only" "report-uri /api/security/csp-reports"

  if [[ "$BASE_URL" == https://* ]]; then
    assert_single_header "$headers" "Strict-Transport-Security" "max-age=15552000; includeSubDomains"
  fi

  echo "PASS: $label ($status)"
}

check_url frontend "/"
check_url api "/api/healthz"
check_url not_found "/__studyhub_security_header_probe_not_found__"

echo "security headers verified for $BASE_URL"
