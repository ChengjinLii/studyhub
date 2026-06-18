#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
PYTHON_BIN="${STUDYHUB_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

section() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$1"
}

run() {
  local label="$1"
  shift
  section "$label"
  "$@"
}

cd "$ROOT_DIR"

run "git status" git status --short --branch
run "shell script syntax" bash "$ROOT_DIR/scripts/check-shell-scripts.sh"
run "sensitive file guard" bash "$ROOT_DIR/scripts/security/check-sensitive-files.sh"
run "clean generated artifacts before checks" bash "$ROOT_DIR/scripts/clean-generated.sh" --source
export STUDYHUB_CODE_SIZE_ALLOW_FRONTEND_BUILD="${STUDYHUB_CODE_SIZE_ALLOW_FRONTEND_BUILD:-1}"
run "code size budget" node "$ROOT_DIR/scripts/check-code-size.mjs"

if [[ -x "$PYTHON_BIN" ]]; then
  run "backend ruff" "$PYTHON_BIN" -m ruff check "$ROOT_DIR/backend/app" "$ROOT_DIR/backend/tests"
  run "backend tests" "$PYTHON_BIN" -m pytest -q "$ROOT_DIR/backend/tests"
else
  echo "warning: skipping backend checks; missing Python interpreter: $PYTHON_BIN" >&2
fi

run "frontend check" npm --prefix "$FRONTEND_DIR" run check
run "frontend strict typecheck subset" npm --prefix "$FRONTEND_DIR" run typecheck:strict
run "frontend unit tests" npm --prefix "$FRONTEND_DIR" run test:unit
run "frontend critical tests" npm --prefix "$FRONTEND_DIR" run test:critical -- --reporter=line
run "clean generated artifacts after tests" bash "$ROOT_DIR/scripts/clean-generated.sh" --source

section "pre-push check passed"
