#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

sudo -n install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-staged-upload-cleanup.service" \
  /etc/systemd/system/studyhub-staged-upload-cleanup.service
sudo -n install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-staged-upload-cleanup.timer" \
  /etc/systemd/system/studyhub-staged-upload-cleanup.timer
sudo -n systemctl daemon-reload
sudo -n systemctl start studyhub-staged-upload-cleanup.service
sudo -n systemctl enable --now studyhub-staged-upload-cleanup.timer
echo "staged upload cleanup passed; timer enabled"
