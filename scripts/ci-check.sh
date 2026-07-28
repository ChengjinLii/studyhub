#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
PYTHON_BIN="${STUDYHUB_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
GENERATED_CLEAN_MODE="${STUDYHUB_CI_CLEAN_MODE:-source}"

case "$GENERATED_CLEAN_MODE" in
  source|all)
    ;;
  *)
    echo "STUDYHUB_CI_CLEAN_MODE must be source or all; got $GENERATED_CLEAN_MODE"
    exit 2
    ;;
esac

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

run "shell script syntax" bash "$ROOT_DIR/scripts/check-shell-scripts.sh"
run "sensitive file guard" bash "$ROOT_DIR/scripts/security/check-sensitive-files.sh"
run "clean generated artifacts" bash "$ROOT_DIR/scripts/clean-generated.sh" "--$GENERATED_CLEAN_MODE"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "missing Python interpreter: $PYTHON_BIN"
  exit 1
fi

run "runtime version alignment" env STUDYHUB_PYTHON_BIN="$PYTHON_BIN" bash "$ROOT_DIR/scripts/check-runtime-versions.sh"

run "backend ruff" "$PYTHON_BIN" -m ruff check "$BACKEND_DIR/app" "$BACKEND_DIR/tests"
mkdir -p "$ROOT_DIR/reports/coverage"
run "backend pytest with coverage report" "$PYTHON_BIN" -m pytest "$BACKEND_DIR/tests" --cov="$BACKEND_DIR/app" --cov-report=term-missing --cov-report=xml:"$ROOT_DIR/reports/coverage/backend-coverage.xml"
run "frontend typecheck and lint" npm --prefix "$FRONTEND_DIR" run check
run "frontend strict typecheck subset" npm --prefix "$FRONTEND_DIR" run typecheck:strict
run "frontend unit tests" npm --prefix "$FRONTEND_DIR" run test:unit
run "frontend critical mock tests" npm --prefix "$FRONTEND_DIR" run test:critical
run "frontend production critical tests" npm --prefix "$FRONTEND_DIR" run test:critical:prod
run "clean generated artifacts after tests" bash "$ROOT_DIR/scripts/clean-generated.sh" "--$GENERATED_CLEAN_MODE"

if [[ "$GENERATED_CLEAN_MODE" == "source" ]]; then
  export STUDYHUB_CODE_SIZE_ALLOW_FRONTEND_BUILD="${STUDYHUB_CODE_SIZE_ALLOW_FRONTEND_BUILD:-1}"
fi
run "code size and generated artifact budget" node "$ROOT_DIR/scripts/check-code-size.mjs"

section "ci check passed"
