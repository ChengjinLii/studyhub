#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if ! command -v clamscan >/dev/null 2>&1; then
  echo "clamscan is required; install clamav before enabling material scans"
  exit 1
fi
if ! clamscan --version >/dev/null 2>&1; then
  echo "clamscan signature database is not ready"
  exit 1
fi
install -d -m 0700 "$ROOT_DIR/private/quarantine"
sudo -n install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-material-scan.service" \
  /etc/systemd/system/studyhub-material-scan.service
sudo -n install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-material-scan.timer" \
  /etc/systemd/system/studyhub-material-scan.timer
sudo -n systemctl daemon-reload
sudo -n systemctl start studyhub-material-scan.service
sudo -n systemctl enable --now studyhub-material-scan.timer
echo "material scanner passed; timer enabled"
