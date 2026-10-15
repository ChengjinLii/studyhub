#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${STUDYHUB_RELEASE_ROOT:-/data/studyhub-runtime}/current"
"$RUNTIME_DIR/.venv/bin/python" -c 'import pypdfium2; import ctypes; ctypes.CDLL("libseccomp.so.2")'
# Run only after the production DB backup and a single-file preview smoke pass.
install -d -m 0700 "$ROOT_DIR/private/preview-work"
sudo -n install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-material-preview.service" /etc/systemd/system/
sudo -n install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-material-preview.timer" /etc/systemd/system/
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now studyhub-material-preview.timer
echo "Deferred preview timer enabled; uploads never wait for rendering."
