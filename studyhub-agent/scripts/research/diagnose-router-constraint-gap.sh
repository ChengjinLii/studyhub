#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
PYTHON="${STUDYHUB_BACKEND_PYTHON:-$WORKSPACE_ROOT/backend/.venv/bin/python}"
PILOT_ROOT="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_grpo_pilot_v1"
EVAL_ROOT="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_pilot_v1"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-constraint-diagnostic"

cd "$ROOT_DIR"
PYTHONPATH="$WORKSPACE_ROOT/backend:$ROOT_DIR" "$PYTHON" -m ml.agentic_platform.rl.diagnose_constraint_gap \
  --states "$PILOT_ROOT/states.jsonl" \
  --baseline "$EVAL_ROOT/test/baseline_sft/predictions.jsonl" \
  --candidate "$EVAL_ROOT/test/seed_3407/predictions.jsonl" \
  --output "$EVAL_ROOT/gate/constraint_gap_diagnostic_v2.json"
