#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
MODEL="$ROOT_DIR/training_artifacts/studyhub_agent_sft/qwen35_2b_router_v1_7_merged"
DATASET="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_rl_maturity_v2"
OUTPUT="$DATASET/reference"
GPU_ID="${STUDYHUB_RL_GPU_ID:-0}"

if [[ -e "$OUTPUT" ]]; then
  echo "reference output already exists; refusing to overwrite: $OUTPUT" >&2
  exit 2
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-maturity-v2-reference"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT_DIR"
CUDA_VISIBLE_DEVICES="$GPU_ID" PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
  -m ml.agentic_platform.rl.maturity_v2.reference_cache \
  --model "$MODEL" \
  --train "$DATASET/train.jsonl" \
  --output-dir "$OUTPUT" \
  --device cuda:0 \
  --batch-size 1 \
  --max-prompt-tokens 4096 \
  --temperature 1.0
