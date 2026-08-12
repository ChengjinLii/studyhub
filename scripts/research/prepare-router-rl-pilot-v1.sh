#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_PYTHON="${STUDYHUB_BACKEND_PYTHON:-$ROOT_DIR/backend/.venv/bin/python}"
CONFIG="${1:-$ROOT_DIR/ml/agentic_platform/rl/configs/router_grpo_pilot_v1.json}"
DATA_ROOT="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_grpo_pilot_v1"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-preparation"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT_DIR"
PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$BACKEND_PYTHON" \
  -m ml.agentic_platform.rl.build_router_rl_pilot_v1
PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$BACKEND_PYTHON" \
  -m ml.agentic_platform.rl.judge_calibration \
  --dataset "$DATA_ROOT/states.jsonl" \
  --output "$DATA_ROOT/judge_calibration.json" \
  --maximum-cases 48 \
  --fail-on-calibration
PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$BACKEND_PYTHON" \
  -m ml.agentic_platform.rl.freeze_inputs \
  --config "$CONFIG" \
  --output "$DATA_ROOT/input_lock.json"
