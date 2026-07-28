#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
PYTHON_BIN="${STUDYHUB_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
RUN_RUNTIME_CHECKS="${STUDYHUB_PREDEPLOY_RUNTIME_CHECKS:-auto}"
RUN_PRODUCTION_CHECKS="${STUDYHUB_PREDEPLOY_PRODUCTION_CHECKS:-auto}"
GENERATED_CLEAN_MODE="${STUDYHUB_PREDEPLOY_CLEAN_MODE:-source}"
REQUIRED_SYSTEMD_SERVICES="${STUDYHUB_PREDEPLOY_REQUIRED_SYSTEMD_SERVICES:-studyhub-backend.service studyhub-frontend.service studyhub-worker.service}"

validate_bool_auto() {
  local name="$1"
  local value="$2"
  case "$value" in
    0|1|false|true|auto)
      ;;
    *)
      echo "$name must be one of: auto, 1, true, 0, false; got $value"
      exit 2
      ;;
  esac
}

case "$GENERATED_CLEAN_MODE" in
  source|all)
    ;;
  *)
    echo "STUDYHUB_PREDEPLOY_CLEAN_MODE must be source or all; got $GENERATED_CLEAN_MODE"
    exit 2
    ;;
esac
validate_bool_auto "STUDYHUB_PREDEPLOY_RUNTIME_CHECKS" "$RUN_RUNTIME_CHECKS"
validate_bool_auto "STUDYHUB_PREDEPLOY_PRODUCTION_CHECKS" "$RUN_PRODUCTION_CHECKS"
for service in $REQUIRED_SYSTEMD_SERVICES; do
  if ! [[ "$service" =~ ^[A-Za-z0-9_.@-]+[.]service$ ]]; then
    echo "STUDYHUB_PREDEPLOY_REQUIRED_SYSTEMD_SERVICES entries must be systemd .service names; got $service"
    exit 2
  fi
done

section() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$1"
}

run() {
  local label="$1"
  shift
  section "$label"
  "$@"
}

run_optional() {
  local label="$1"
  shift
  section "$label"
  if "$@"; then
    return 0
  fi
  echo "optional check failed: $label"
  return 1
}

cd "$ROOT_DIR"

run "shell script syntax" bash "$ROOT_DIR/scripts/check-shell-scripts.sh"

run "sensitive file guard" bash "$ROOT_DIR/scripts/security/check-sensitive-files.sh"

run "clean generated artifacts" bash "$ROOT_DIR/scripts/clean-generated.sh" "--$GENERATED_CLEAN_MODE"

section "git working tree"
git status --short

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "missing Python interpreter: $PYTHON_BIN"
  exit 1
fi

run "backend ruff" "$PYTHON_BIN" -m ruff check "$BACKEND_DIR/app" "$BACKEND_DIR/tests"

mkdir -p "$ROOT_DIR/reports/coverage"
run "backend pytest with coverage report" "$PYTHON_BIN" -m pytest "$BACKEND_DIR/tests" --cov="$BACKEND_DIR/app" --cov-report=term-missing --cov-report=xml:"$ROOT_DIR/reports/coverage/backend-coverage.xml"

run "frontend typecheck and lint" npm --prefix "$FRONTEND_DIR" run check

run "frontend strict typecheck subset" npm --prefix "$FRONTEND_DIR" run typecheck:strict

run "frontend unit tests" npm --prefix "$FRONTEND_DIR" run test:unit

run "frontend critical mock tests" npm --prefix "$FRONTEND_DIR" run test:critical

run "frontend production critical tests" npm --prefix "$FRONTEND_DIR" run test:critical:prod

run "clean generated artifacts after frontend tests" bash "$ROOT_DIR/scripts/clean-generated.sh" "--$GENERATED_CLEAN_MODE"

if [[ "$GENERATED_CLEAN_MODE" == "source" ]]; then
  export STUDYHUB_CODE_SIZE_ALLOW_FRONTEND_BUILD="${STUDYHUB_CODE_SIZE_ALLOW_FRONTEND_BUILD:-1}"
fi
run "code size and generated artifact budget" node "$ROOT_DIR/scripts/check-code-size.mjs"

if [[ "$RUN_PRODUCTION_CHECKS" == "0" || "$RUN_PRODUCTION_CHECKS" == "false" ]]; then
  section "production preflight"
  echo "skipped: STUDYHUB_PREDEPLOY_PRODUCTION_CHECKS=$RUN_PRODUCTION_CHECKS"
elif [[ -f "$ROOT_DIR/private/.env.production" ]]; then
  run "production preflight" bash "$ROOT_DIR/scripts/runtime/production-preflight.sh"
else
  section "production preflight"
  echo "skipped: private/.env.production is not present"
fi

if command -v nginx >/dev/null 2>&1; then
  if [[ "$RUN_RUNTIME_CHECKS" == "1" || "$RUN_RUNTIME_CHECKS" == "true" || "$RUN_RUNTIME_CHECKS" == "auto" ]]; then
    run "nginx config test" nginx -t
  fi
else
  section "nginx config test"
  echo "skipped: nginx command is not available"
fi

if [[ "$RUN_RUNTIME_CHECKS" == "0" || "$RUN_RUNTIME_CHECKS" == "false" ]]; then
  section "systemd service status"
  echo "skipped: STUDYHUB_PREDEPLOY_RUNTIME_CHECKS=$RUN_RUNTIME_CHECKS"
elif command -v systemctl >/dev/null 2>&1; then
  section "systemd service status"
  systemd_failures=0
  for service in studyhub-backend.service studyhub-frontend.service studyhub-worker.service studyhub-scheduler.service; do
    if systemctl list-unit-files "$service" >/dev/null 2>&1; then
      status_value="$(systemctl is-active "$service" || true)"
      echo "$service: $status_value"
      for required_service in $REQUIRED_SYSTEMD_SERVICES; do
        if [[ "$service" == "$required_service" && "$status_value" != "active" ]]; then
          echo "required systemd service is not active: $service"
          systemd_failures=$((systemd_failures + 1))
        fi
      done
    else
      echo "$service: not installed"
      for required_service in $REQUIRED_SYSTEMD_SERVICES; do
        if [[ "$service" == "$required_service" ]]; then
          echo "required systemd service is not installed: $service"
          systemd_failures=$((systemd_failures + 1))
        fi
      done
    fi
  done
  if (( systemd_failures > 0 )); then
    exit 1
  fi
else
  section "systemd service status"
  echo "skipped: systemctl command is not available"
fi

section "predeploy check passed"
