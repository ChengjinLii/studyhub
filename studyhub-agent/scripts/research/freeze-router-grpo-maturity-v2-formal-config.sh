#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
PYTHON="${STUDYHUB_BACKEND_PYTHON:-$WORKSPACE_ROOT/backend/.venv/bin/python}"
EVAL_ROOT="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-maturity-v2-formal-config"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT_DIR"
PYTHONPATH="$WORKSPACE_ROOT/backend:$ROOT_DIR" "$PYTHON" \
  -m ml.agentic_platform.rl.maturity_v2.formal_config \
  --primary-results "$EVAL_ROOT/grpo_sweep/sweep_results.json" \
  --failed-scale-results "$EVAL_ROOT/grpo_scale_sweep/scale_sweep_results.json" \
  --stability-results "$EVAL_ROOT/grpo_stability_sweep/stability_sweep_results.json" \
  --output "$ROOT_DIR/ml/agentic_platform/rl/configs/router_grpo_maturity_v2_formal.json"
