#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPORT_DIR="$ROOT_DIR/private/reports/finance"

install -d -m 0700 "$REPORT_DIR"
sudo -n install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-finance-reconcile.service" \
  /etc/systemd/system/studyhub-finance-reconcile.service
sudo -n install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-finance-reconcile.timer" \
  /etc/systemd/system/studyhub-finance-reconcile.timer
sudo -n systemctl daemon-reload
sudo -n systemctl start studyhub-finance-reconcile.service
sudo -n systemctl enable --now studyhub-finance-reconcile.timer
echo "finance reconciliation passed; daily timer enabled"
