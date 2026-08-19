#!/usr/bin/env bash
set -euo pipefail

# Immutable segment recovery, model-token provenance, DeepResearch child
# linkage, data classification, and training adapter contracts.  This is
# intentionally offline and does not collect or export production data.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
BACKEND_DIR="$WORKSPACE_ROOT/backend"
PYTHON_BIN="${STUDYHUB_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

fail() {
  printf 'trajectory-integrity: %s\n' "$*" >&2
  exit 1
}

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v "$PYTHON_BIN" 2>/dev/null || true)"
fi
[[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]] || fail "missing Python interpreter"

cd "$BACKEND_DIR"
"$PYTHON_BIN" -m pytest -q \
  tests/agentic_platform/test_domain_hashing.py \
  tests/agentic_platform/test_runtime_model_trace.py \
  tests/agentic_platform/test_deepresearch_transitions.py \
  tests/agentic_platform/test_durable_agent_storage.py \
  tests/agentic_platform/test_trajectory_export.py \
  tests/agentic_platform/test_data_governance.py \
  tests/agentic_platform/test_training_adapters.py

printf 'Trajectory integrity checks passed.\n'
