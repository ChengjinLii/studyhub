#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:---source}"
ENVIRONMENT="${STUDYHUB_ENVIRONMENT:-}"
PRODUCTION_CLEAN_CONFIRM="${YES_PRODUCTION_CLEAN_FRONTEND_BUILD:-}"

usage() {
  cat <<'EOF'
Usage: bash scripts/clean-generated.sh [--source|--all]

  --source  Clean source-tree caches and test artifacts, keep frontend/.next.
  --all     Also remove frontend/.next; use only when a frontend rebuild is planned.

Production guard:
  --all refuses to remove frontend/.next when STUDYHUB_ENVIRONMENT=production
  or private/.env.production exists, unless YES_PRODUCTION_CLEAN_FRONTEND_BUILD
  is set to I_UNDERSTAND_REBUILD_FRONTEND.
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

if [[ "$MODE" == "--all" ]]; then
  if [[ "${ENVIRONMENT,,}" == "production" || -f "$ROOT_DIR/private/.env.production" ]]; then
    if [[ "$PRODUCTION_CLEAN_CONFIRM" != "I_UNDERSTAND_REBUILD_FRONTEND" ]]; then
      echo "refusing to remove frontend/.next on a production-capable tree."
      echo "Use --source to keep the active frontend build, or set YES_PRODUCTION_CLEAN_FRONTEND_BUILD=I_UNDERSTAND_REBUILD_FRONTEND when a rebuild is planned."
      exit 2
    fi
  fi
fi

rm -rf \
  frontend/test-results \
  frontend/playwright-report \
  frontend/.next-playwright-dev \
  frontend/.next-playwright-prod \
  backend/.pytest_cache \
  .pytest_cache

if [[ "$MODE" == "--all" ]]; then
  rm -rf frontend/.next
fi

find backend -type d -name '__pycache__' -prune -exec rm -rf {} +
find backend -type f -name '*.pyc' -delete

if [[ "$MODE" == "--all" ]]; then
  echo "Generated caches, test artifacts, and frontend build output cleaned."
else
  echo "Generated source caches and test artifacts cleaned; frontend/.next kept."
fi
