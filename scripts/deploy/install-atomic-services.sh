#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_ROOT="${STUDYHUB_RELEASE_ROOT:-/data/studyhub-runtime}"
CURRENT_ROOT="$RUNTIME_ROOT/current"
APP_USER="${STUDYHUB_APP_USER:-$(id -un)}"
NPM_BIN="${STUDYHUB_NPM_BIN:-$(command -v npm)}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$ROOT_DIR/private/backups/atomic-services-$STAMP"

if [[ "$EUID" -eq 0 ]]; then
  echo "run this installer as the application user; it uses sudo only for system files"
  exit 2
fi
if [[ ! -x "$NPM_BIN" ]]; then
  echo "npm executable not found: $NPM_BIN"
  exit 1
fi

install -d -m 0755 "$RUNTIME_ROOT/releases"
if [[ ! -e "$CURRENT_ROOT" ]]; then
  ln -s "$ROOT_DIR" "$CURRENT_ROOT"
fi
install -d -m 0700 "$BACKUP_DIR"

for path in \
  /etc/systemd/system/studyhub-backend.service.d/security.conf \
  /etc/systemd/system/studyhub-frontend.service.d/runtime.conf \
  /etc/systemd/system/studyhub-worker.service.d/atomic-release.conf; do
  if sudo -n test -f "$path"; then
    sudo -n cp -a "$path" "$BACKUP_DIR/$(basename "$(dirname "$path")")-$(basename "$path")"
  fi
done

render_install() {
  local source="$1"
  local destination="$2"
  local temporary
  temporary="$(mktemp)"
  sed \
    -e "s|__CURRENT_ROOT__|$CURRENT_ROOT|g" \
    -e "s|__NPM_BIN__|$NPM_BIN|g" \
    "$source" > "$temporary"
  sudo -n install -D -m 0644 "$temporary" "$destination"
  rm -f "$temporary"
}

render_install "$ROOT_DIR/deploy/systemd/studyhub-atomic-backend.conf.in" \
  /etc/systemd/system/studyhub-backend.service.d/security.conf
render_install "$ROOT_DIR/deploy/systemd/studyhub-atomic-frontend.conf.in" \
  /etc/systemd/system/studyhub-frontend.service.d/runtime.conf
render_install "$ROOT_DIR/deploy/systemd/studyhub-atomic-worker.conf.in" \
  /etc/systemd/system/studyhub-worker.service.d/atomic-release.conf

sudo -n systemctl daemon-reload
sudo -n systemctl restart studyhub-backend.service
for _attempt in $(seq 1 45); do
  if curl -fsS --max-time 2 http://127.0.0.1:8311/api/readyz >/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS --max-time 2 http://127.0.0.1:8311/api/readyz >/dev/null
sudo -n systemctl restart studyhub-worker.service studyhub-frontend.service
echo "atomic service paths installed; current=$CURRENT_ROOT -> $(readlink -f "$CURRENT_ROOT")"
