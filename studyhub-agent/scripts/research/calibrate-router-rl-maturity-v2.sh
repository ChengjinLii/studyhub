#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
PYTHON="${STUDYHUB_BACKEND_PYTHON:-$WORKSPACE_ROOT/backend/.venv/bin/python}"
DATASET="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_rl_maturity_v2"
OUTPUT="$DATASET/calibration"

if [[ -e "$OUTPUT" ]]; then
  echo "calibration output already exists; refusing to overwrite: $OUTPUT" >&2
  exit 2
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-maturity-v2-calibration"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT_DIR"
PYTHONPATH="$WORKSPACE_ROOT/backend:$ROOT_DIR" "$PYTHON" \
  -m ml.agentic_platform.rl.maturity_v2.calibration \
  --validation "$DATASET/validation.jsonl" \
  --output-dir "$OUTPUT"
