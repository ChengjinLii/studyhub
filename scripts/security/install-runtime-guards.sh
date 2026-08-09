#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SITE_CONFIG="${STUDYHUB_NGINX_SITE_CONFIG:-/etc/nginx/sites-available/studyhub-ip}"
SSH_PORT="${STUDYHUB_SSH_PORT:-22}"
ENABLE_UFW="${STUDYHUB_ENABLE_UFW:-0}"
APPLY="${1:-}"

if [[ "$APPLY" != "--apply" ]]; then
  echo "usage: sudo STUDYHUB_ENABLE_UFW=1 $0 --apply"
  echo "installs nginx guards, backend concurrency limits, and the local monitor"
  exit 2
fi
if [[ "$EUID" -ne 0 ]]; then
  echo "run as root (or with sudo)"
  exit 1
fi
if ! [[ "$SSH_PORT" =~ ^[1-9][0-9]*$ ]] || ((SSH_PORT > 65535)); then
  echo "STUDYHUB_SSH_PORT must be a TCP port between 1 and 65535"
  exit 2
fi
case "$ENABLE_UFW" in
  0|1|false|true) ;;
  *)
    echo "STUDYHUB_ENABLE_UFW must be one of: 0, 1, false, true"
    exit 2
    ;;
esac
if [[ ! -f "$SITE_CONFIG" ]]; then
  echo "missing nginx site config: $SITE_CONFIG"
  exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="$ROOT_DIR/private/backups/runtime-guards-$timestamp"
install -d -m 0700 "$backup_dir"
cp -a "$SITE_CONFIG" "$backup_dir/nginx-site.conf"
had_zones=0
had_server_snippet=0
if [[ -f /etc/nginx/conf.d/studyhub-abuse-zones.conf ]]; then
  had_zones=1
  cp -a /etc/nginx/conf.d/studyhub-abuse-zones.conf "$backup_dir/"
fi
if [[ -f /etc/nginx/snippets/studyhub-abuse-server.conf ]]; then
  had_server_snippet=1
  cp -a /etc/nginx/snippets/studyhub-abuse-server.conf "$backup_dir/"
fi

rollback_nginx() {
  echo "nginx guard installation failed; restoring previous configuration" >&2
  cp -a "$backup_dir/nginx-site.conf" "$SITE_CONFIG"
  if ((had_zones)); then
    cp -a "$backup_dir/studyhub-abuse-zones.conf" /etc/nginx/conf.d/studyhub-abuse-zones.conf
  else
    rm -f /etc/nginx/conf.d/studyhub-abuse-zones.conf
  fi
  if ((had_server_snippet)); then
    cp -a "$backup_dir/studyhub-abuse-server.conf" /etc/nginx/snippets/studyhub-abuse-server.conf
  else
    rm -f /etc/nginx/snippets/studyhub-abuse-server.conf
  fi
  nginx -t || true
}
trap rollback_nginx ERR

install -m 0644 "$ROOT_DIR/deploy/nginx/studyhub-abuse-zones.conf" /etc/nginx/conf.d/studyhub-abuse-zones.conf
install -m 0644 "$ROOT_DIR/deploy/nginx/studyhub-abuse-server.conf" /etc/nginx/snippets/studyhub-abuse-server.conf

if ! grep -Fq 'include /etc/nginx/snippets/studyhub-abuse-server.conf;' "$SITE_CONFIG"; then
  python3 - "$SITE_CONFIG" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
updated: list[str] = []
server_names = 0
for line in lines:
    updated.append(line)
    if line.lstrip().startswith("server_name ") and line.rstrip().endswith(";"):
        indent = line[: len(line) - len(line.lstrip())]
        updated.append(f"{indent}include /etc/nginx/snippets/studyhub-abuse-server.conf;")
        server_names += 1
if server_names == 0:
    raise SystemExit("nginx site contains no server_name directive")
path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
fi

nginx -t
systemctl reload nginx
trap - ERR

install -d -m 0755 /etc/systemd/system/studyhub-backend.service.d
install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-backend-hardening.conf" /etc/systemd/system/studyhub-backend.service.d/security.conf
install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-abuse-monitor.service" /etc/systemd/system/studyhub-abuse-monitor.service
install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-abuse-monitor.timer" /etc/systemd/system/studyhub-abuse-monitor.timer
systemctl daemon-reload
systemctl enable --now studyhub-abuse-monitor.timer

if [[ "$ENABLE_UFW" == "1" || "$ENABLE_UFW" == "true" ]]; then
  command -v ufw >/dev/null 2>&1 || { echo "ufw is not installed"; exit 1; }
  ufw default deny incoming
  ufw default allow outgoing
  ufw limit "$SSH_PORT/tcp" comment 'SSH rate limited'
  ufw allow 80/tcp comment 'StudyHub HTTP'
  ufw allow 443/tcp comment 'StudyHub HTTPS'
  ufw --force enable
fi

echo "runtime guards installed; backup: $backup_dir"
echo "restart studyhub-backend.service after application checks to activate the concurrency cap"
