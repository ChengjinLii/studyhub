#!/usr/bin/env bash
set -euo pipefail

BACKEND_BASE="${1:-http://127.0.0.1:8211}"
curl --fail --silent --show-error "${BACKEND_BASE%/}/api/healthz"
curl --fail --silent --show-error "${BACKEND_BASE%/}/api/readyz" >/dev/null
