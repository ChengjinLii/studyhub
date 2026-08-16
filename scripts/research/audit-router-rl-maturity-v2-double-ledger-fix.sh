#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${STUDYHUB_BACKEND_PYTHON:-$ROOT_DIR/backend/.venv/bin/python}"
EVAL_ROOT="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_maturity_v2"
BEFORE="$EVAL_ROOT/protocol_revisions/pre_double_ledger_fix_20260812/validation/robustness/frozen_candidate"
AFTER="$EVAL_ROOT/validation/robustness/frozen_candidate"

cd "$ROOT_DIR"
PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$PYTHON" \
  -m ml.agentic_platform.rl.maturity_v2.double_ledger_audit \
  --before-summary "$BEFORE/summary.json" \
  --before-predictions "$BEFORE/predictions.jsonl" \
  --after-summary "$AFTER/summary.json" \
  --after-predictions "$AFTER/predictions.jsonl" \
  --implementation \
    "$ROOT_DIR/backend/app/services/agent_router_constraint_service.py" \
    "$ROOT_DIR/ml/agentic_platform/rl/maturity_v2/evaluate.py" \
    "$ROOT_DIR/ml/agentic_platform/rl/maturity_v2/robustness.py" \
  --output "$EVAL_ROOT/gate/double_ledger_fix_audit.json"
