#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

rm -rf \
  frontend/.next \
  frontend/test-results \
  frontend/playwright-report \
  backend/.pytest_cache \
  .pytest_cache

find backend ai_platform -type d -name '__pycache__' -prune -exec rm -rf {} +
find backend ai_platform -type f -name '*.pyc' -delete

echo "Generated caches and test artifacts cleaned."
