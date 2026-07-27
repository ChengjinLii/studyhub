#!/usr/bin/env bash
set -euo pipefail

# Fixture integration coverage for the opt-in execution plane.  It exercises
# Admin run/job state, leases, dispatch/resume/cancel, the durable factory, and
# retry paths without calling an external model provider.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
PYTHON_BIN="${STUDYHUB_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

fail() {
  printf 'agentic-execution-e2e: %s\n' "$*" >&2
  exit 1
}

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v "$PYTHON_BIN" 2>/dev/null || true)"
fi
[[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]] || fail "missing Python interpreter"

cd "$BACKEND_DIR"
"$PYTHON_BIN" -m pytest -q \
  tests/agentic_platform/test_execution_worker.py \
  tests/agentic_platform/test_durable_agent_storage.py::test_production_factory_builds_kernel_with_only_durable_runtime_adapters \
  tests/test_admin_agentic_runs.py

printf 'Agentic execution E2E fixture checks passed.\n'
