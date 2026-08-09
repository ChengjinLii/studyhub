#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PASSWORD_FILE="${STUDYHUB_REDIS_PASSWORD_FILE:-$ROOT_DIR/private/redis-studyhub-password}"

command -v redis-cli >/dev/null 2>&1 || { echo "redis-cli is required" >&2; exit 1; }
[[ -s "$PASSWORD_FILE" ]] || { echo "missing Redis password file: $PASSWORD_FILE" >&2; exit 1; }
redis_password="$(tr -d '\r\n' <"$PASSWORD_FILE")"

systemctl is-active --quiet redis-server.service
REDISCLI_AUTH="$redis_password" redis-cli --user studyhub --no-auth-warning ping | grep -qx PONG

info="$(REDISCLI_AUTH="$redis_password" redis-cli --user studyhub --no-auth-warning info memory)"
printf '%s\n' "$info" | grep -q '^maxmemory:67108864'
printf '%s\n' "$info" | grep -q '^maxmemory_policy:noeviction'

listen_addresses="$(ss -lnt | awk '$4 ~ /(^|:)6379$/ {print $4}')"
[[ -n "$listen_addresses" ]] || { echo "Redis is not listening" >&2; exit 1; }
if printf '%s\n' "$listen_addresses" | grep -Eq '(^|\[)(0\.0\.0\.0|::)(\]|):6379$'; then
  echo "Redis listens on a wildcard address: $listen_addresses" >&2
  exit 1
fi

memory_max="$(systemctl show redis-server.service -p MemoryMax --value)"
[[ "$memory_max" == "134217728" ]] || { echo "unexpected Redis MemoryMax: $memory_max" >&2; exit 1; }

echo "Redis runtime check passed (64MB data, 128MB process, loopback only)."
