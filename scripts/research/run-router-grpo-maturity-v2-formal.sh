#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
COMMAND="${1:?usage: $0 <pause|resume> <seed> [gpu-id]}"
SEED="${2:?usage: $0 <pause|resume> <seed> [gpu-id]}"
GPU_ID="${3:-0}"
CONFIG="$ROOT_DIR/ml/agentic_platform/rl/configs/router_grpo_maturity_v2_formal.json"
RUN_DIR="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_rl_maturity_v2/experiments/grpo_formal/seed_$SEED"
CHECKPOINT="$RUN_DIR/checkpoints/update_0100"

case "$SEED" in
  3407|7703|9109|6209|11213) ;;
  *)
    echo "seed must be one of: 3407 7703 9109 6209 11213" >&2
    exit 2
    ;;
esac
if [[ ! -f "$CONFIG" ]]; then
  echo "formal config is not frozen: $CONFIG" >&2
  exit 2
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-maturity-v2-formal-training"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT_DIR"
case "$COMMAND" in
  pause)
    if [[ -e "$RUN_DIR/partial_status.json" || -e "$RUN_DIR/run_summary.json" ]]; then
      echo "formal seed already started; use resume only after auditing: $RUN_DIR" >&2
      exit 2
    fi
    CUDA_VISIBLE_DEVICES="$GPU_ID" PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
      -m ml.agentic_platform.rl.maturity_v2.train_grpo \
      --config "$CONFIG" \
      --seed "$SEED" \
      --output-dir "$RUN_DIR" \
      --stop-after 100
    ;;
  resume)
    if [[ ! -f "$RUN_DIR/partial_status.json" || ! -f "$CHECKPOINT/checkpoint.json" ]]; then
      echo "the audited update-100 pause checkpoint is missing: $CHECKPOINT" >&2
      exit 2
    fi
    if [[ -e "$RUN_DIR/run_summary.json" ]]; then
      echo "formal seed is already finalized: $RUN_DIR" >&2
      exit 2
    fi
    CUDA_VISIBLE_DEVICES="$GPU_ID" PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
      -m ml.agentic_platform.rl.maturity_v2.train_grpo \
      --config "$CONFIG" \
      --seed "$SEED" \
      --output-dir "$RUN_DIR" \
      --resume-from "$CHECKPOINT"
    ;;
  *)
    echo "command must be pause or resume" >&2
    exit 2
    ;;
esac
