#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${STUDYHUB_REDIS_ENV_FILE:-$ROOT_DIR/private/.env.production}"
APPLY="${1:-}"

if [[ "$APPLY" != "--apply" ]]; then
  echo "usage: sudo $0 --apply"
  echo "installs a loopback-only, memory-bounded Redis for expiring StudyHub state"
  exit 2
fi
if [[ "$EUID" -ne 0 ]]; then
  echo "run as root (or with sudo)" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing private environment file: $ENV_FILE" >&2
  exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="$ROOT_DIR/private/backups/redis-$timestamp"
install -d -m 0700 -o ubuntu -g ubuntu "$backup_dir"
cp -a "$ENV_FILE" "$backup_dir/environment.before"
had_config=0
had_acl=0
had_override=0
had_password=0
redis_was_active=0
if [[ -f /etc/redis/studyhub.conf ]]; then
  had_config=1
  cp -a /etc/redis/studyhub.conf "$backup_dir/redis-config.before"
fi
if [[ -f /etc/redis/studyhub-users.acl ]]; then
  had_acl=1
  cp -a /etc/redis/studyhub-users.acl "$backup_dir/redis-acl.before"
fi
if [[ -f /etc/systemd/system/redis-server.service.d/studyhub.conf ]]; then
  had_override=1
  cp -a /etc/systemd/system/redis-server.service.d/studyhub.conf "$backup_dir/systemd-override.before"
fi
if [[ -s "$ROOT_DIR/private/redis-studyhub-password" ]]; then
  had_password=1
fi
if systemctl is-active --quiet redis-server.service 2>/dev/null; then
  redis_was_active=1
fi

restore_or_remove() {
  local had_previous="$1"
  local backup="$2"
  local destination="$3"
  if [[ "$had_previous" == "1" ]]; then
    cp -a "$backup" "$destination"
  else
    rm -f "$destination"
  fi
}

rollback_runtime() {
  echo "Redis installation failed; restoring previous runtime configuration" >&2
  cp -a "$backup_dir/environment.before" "$ENV_FILE"
  restore_or_remove "$had_config" "$backup_dir/redis-config.before" /etc/redis/studyhub.conf
  restore_or_remove "$had_acl" "$backup_dir/redis-acl.before" /etc/redis/studyhub-users.acl
  restore_or_remove "$had_override" "$backup_dir/systemd-override.before" \
    /etc/systemd/system/redis-server.service.d/studyhub.conf
  if [[ "$had_password" == "0" ]]; then
    rm -f "$ROOT_DIR/private/redis-studyhub-password"
  fi
  systemctl daemon-reload || true
  if [[ "$redis_was_active" == "1" ]]; then
    systemctl restart redis-server.service || true
  else
    systemctl stop redis-server.service || true
  fi
}
trap rollback_runtime ERR

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends redis-server redis-tools

password_file="$ROOT_DIR/private/redis-studyhub-password"
if [[ ! -s "$password_file" ]]; then
  umask 077
  openssl rand -hex 32 >"$password_file"
  chown ubuntu:ubuntu "$password_file"
  chmod 0600 "$password_file"
fi
redis_password="$(tr -d '\r\n' <"$password_file")"
if ! [[ "$redis_password" =~ ^[a-f0-9]{64}$ ]]; then
  echo "invalid Redis password file" >&2
  exit 1
fi

install -d -m 0750 -o root -g redis /etc/redis
install -m 0640 -o root -g redis "$ROOT_DIR/deploy/redis/studyhub.conf" /etc/redis/studyhub.conf
acl_tmp="$(mktemp)"
trap 'rm -f "$acl_tmp"' EXIT
printf '%s\n' \
  'user default off' \
  "user studyhub on >$redis_password ~studyhub-fastapi:* +@all -flushall -flushdb -config -shutdown -debug -module -acl -slaveof -replicaof -save -bgsave -bgrewriteaof -migrate -restore" \
  >"$acl_tmp"
install -m 0640 -o root -g redis "$acl_tmp" /etc/redis/studyhub-users.acl

install -d -m 0755 /etc/systemd/system/redis-server.service.d
install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-redis-hardening.conf" \
  /etc/systemd/system/redis-server.service.d/studyhub.conf

env_tmp="$(mktemp)"
python3 - "$ENV_FILE" "$env_tmp" "$redis_password" <<'PY'
from __future__ import annotations

from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
password = sys.argv[3]
updates = {
    "STUDYHUB_REDIS_URL": f"redis://studyhub:{password}@127.0.0.1:6379/0",
    "STUDYHUB_REDIS_SOCKET_TIMEOUT_SECONDS": "0.5",
    "STUDYHUB_REDIS_CONNECT_TIMEOUT_SECONDS": "0.2",
    "STUDYHUB_RATE_LIMIT_BACKEND": "redis",
    "STUDYHUB_CAPTCHA_BACKEND": "redis",
    "STUDYHUB_SECURITY_STATE_BACKEND": "redis",
    "STUDYHUB_UPLOAD_AUTHORIZATION_REQUIRED": "true",
    "STUDYHUB_PUBLIC_READ_CACHE_BACKEND": "redis",
}
lines = source.read_text(encoding="utf-8").splitlines()
seen: set[str] = set()
rendered: list[str] = []
for line in lines:
    stripped = line.strip()
    if stripped and not stripped.startswith("#") and "=" in line:
        key = line.split("=", 1)[0].strip()
        if key in updates:
            rendered.append(f"{key}={updates[key]}")
            seen.add(key)
            continue
    rendered.append(line)
if rendered and rendered[-1] != "":
    rendered.append("")
rendered.append("# Redis-backed expiring state; installed by scripts/security/install-redis.sh")
for key, value in updates.items():
    if key not in seen:
        rendered.append(f"{key}={value}")
target.write_text("\n".join(rendered) + "\n", encoding="utf-8")
PY
install -m 0600 -o ubuntu -g ubuntu "$env_tmp" "$ENV_FILE"
rm -f "$env_tmp"

systemctl daemon-reload
systemctl enable redis-server.service
systemctl restart redis-server.service

REDISCLI_AUTH="$redis_password" redis-cli --user studyhub --no-auth-warning ping | grep -qx PONG
REDISCLI_AUTH="$redis_password" redis-cli --user studyhub --no-auth-warning \
  set studyhub-fastapi:install-smoke ok EX 10 NX | grep -qx OK
REDISCLI_AUTH="$redis_password" redis-cli --user studyhub --no-auth-warning \
  get studyhub-fastapi:install-smoke | grep -qx ok

if ss -lnt | awk '$4 ~ /(^|:)6379$/ {print $4}' | grep -Eq '(^|\[)(0\.0\.0\.0|::)(\]|):6379$'; then
  echo "Redis unexpectedly listens on a public wildcard address" >&2
  exit 1
fi

trap - ERR
trap - EXIT
rm -f "$acl_tmp"
echo "StudyHub Redis installed; backup: $backup_dir"
echo "Redis credentials were written only to the private environment and password files."
