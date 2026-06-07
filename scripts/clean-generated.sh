#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:---source}"

usage() {
  cat <<'EOF'
Usage: bash scripts/clean-generated.sh [--source|--all]

  --source  Clean source-tree caches and test artifacts, keep frontend/.next.
  --all     Also remove frontend/.next; use only when a frontend rebuild is planned.
EOF
}

case "$MODE" in
  --source|--all)
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage
    exit 2
    ;;
esac

rm -rf \
  frontend/test-results \
  frontend/playwright-report \
  backend/.pytest_cache \
  .pytest_cache

if [[ "$MODE" == "--all" ]]; then
  rm -rf frontend/.next
fi

find backend ai_platform -type d -name '__pycache__' -prune -exec rm -rf {} +
find backend ai_platform -type f -name '*.pyc' -delete

if [[ "$MODE" == "--all" ]]; then
  echo "Generated caches, test artifacts, and frontend build output cleaned."
else
  echo "Generated source caches and test artifacts cleaned; frontend/.next kept."
fi
