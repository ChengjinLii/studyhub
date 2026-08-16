#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
SEED="${1:?usage: $0 <seed> [gpu-id]}"
GPU_ID="${2:-0}"
ARTIFACT_ROOT="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_rl_maturity_v2"
RUN_DIR="$ARTIFACT_ROOT/experiments/grpo_formal/seed_$SEED"
OUTPUT_DIR="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation/grpo_formal/seed_$SEED"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-maturity-v2-formal-evaluation"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT_DIR"
CUDA_VISIBLE_DEVICES="$GPU_ID" PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
  -m ml.agentic_platform.rl.maturity_v2.evaluate \
  --model "$ROOT_DIR/training_artifacts/studyhub_agent_sft/qwen35_2b_router_v1_7_merged" \
  --adapter "$RUN_DIR/adapter" \
  --dataset "$ARTIFACT_ROOT/validation.jsonl" \
  --split validation \
  --output-dir "$OUTPUT_DIR" \
  --device cuda:0 \
  --seed 26081201
