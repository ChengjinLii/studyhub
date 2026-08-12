#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${STUDYHUB_BACKEND_PYTHON:-$ROOT_DIR/backend/.venv/bin/python}"
ARTIFACT_ROOT="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_grpo_pilot_v1"
EVALUATION_ROOT="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_pilot_v1"
OUTPUT_DIR="$EVALUATION_ROOT/gate"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-gate"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

ARGS=()
if [[ "${1:-}" == "--require-test" ]]; then
  ARGS+=("--require-test")
fi

cd "$ROOT_DIR"
PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$PYTHON" -m ml.agentic_platform.rl.gate \
  --repo-root "$ROOT_DIR" \
  --artifact-root "$ARTIFACT_ROOT" \
  --evaluation-root "$EVALUATION_ROOT" \
  --output-dir "$OUTPUT_DIR" \
  "${ARGS[@]}"
