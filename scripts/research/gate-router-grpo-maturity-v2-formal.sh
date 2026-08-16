#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${STUDYHUB_BACKEND_PYTHON:-$ROOT_DIR/backend/.venv/bin/python}"
ARTIFACT_ROOT="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_rl_maturity_v2"
EVAL_ROOT="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_maturity_v2"
COMMAND="${1:-select}"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-maturity-v2-formal-gate"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT_DIR"
if [[ "$COMMAND" == "select" ]]; then
  PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$PYTHON" \
    -m ml.agentic_platform.rl.maturity_v2.formal_gate select \
    --seeds 3407 7703 9109 6209 11213 \
    --baseline-dir "$EVAL_ROOT/validation/baseline_sft" \
    --training-root "$ARTIFACT_ROOT/experiments/grpo_formal" \
    --evaluation-root "$EVAL_ROOT/validation/grpo_formal" \
    --config "$ROOT_DIR/ml/agentic_platform/rl/configs/router_grpo_maturity_v2_formal.json" \
    --acceptance "$ROOT_DIR/ml/agentic_platform/rl/configs/router_rl_maturity_v2_acceptance.json" \
    --output-root "$EVAL_ROOT/gate"
elif [[ "$COMMAND" == "freeze" ]]; then
  PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$PYTHON" \
    -m ml.agentic_platform.rl.maturity_v2.formal_gate freeze \
    --gate "$EVAL_ROOT/gate/formal_validation_gate.json" \
    --baseline-dir "$EVAL_ROOT/validation/baseline_sft" \
    --training-root "$ARTIFACT_ROOT/experiments/grpo_formal" \
    --evaluation-root "$EVAL_ROOT/validation/grpo_formal" \
    --robustness-summary "$EVAL_ROOT/validation/robustness/frozen_candidate/summary.json" \
    --config "$ROOT_DIR/ml/agentic_platform/rl/configs/router_grpo_maturity_v2_formal.json" \
    --acceptance "$ROOT_DIR/ml/agentic_platform/rl/configs/router_rl_maturity_v2_acceptance.json" \
    --output "$EVAL_ROOT/gate/frozen_candidate.json"
else
  echo "usage: $0 <select|freeze>" >&2
  exit 2
fi
