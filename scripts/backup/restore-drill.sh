#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export STUDYHUB_ENVIRONMENT=production
export STUDYHUB_PRIVATE_DIR_PATH="${STUDYHUB_PRIVATE_DIR_PATH:-$ROOT_DIR/private}"
cd "$ROOT_DIR/backend"
exec "$ROOT_DIR/.venv/bin/python" -m app.ops.backup_automation restore-drill
