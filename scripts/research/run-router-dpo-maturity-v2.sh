#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
CONFIG="$ROOT_DIR/ml/agentic_platform/rl/configs/router_dpo_maturity_v2.json"
GPU_ID="${STUDYHUB_RL_GPU_ID:-0}"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-maturity-v2-dpo"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT_DIR"
CUDA_VISIBLE_DEVICES="$GPU_ID" PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
  -m ml.agentic_platform.rl.maturity_v2.train_dpo \
  --config "$CONFIG" \
  --seed 26081201
