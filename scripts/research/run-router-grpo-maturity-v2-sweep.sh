#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
MANIFEST="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_rl_maturity_v2/experiments/grpo_sweep/sweep_manifest.json"
SHARD="${1:?usage: $0 <0|1> [gpu-id]}"
GPU_ID="${2:-$SHARD}"

if [[ "$SHARD" != "0" && "$SHARD" != "1" ]]; then
  echo "shard must be 0 or 1" >&2
  exit 2
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-maturity-v2-sweep"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT_DIR"
CUDA_VISIBLE_DEVICES="$GPU_ID" PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
  -m ml.agentic_platform.rl.maturity_v2.sweep run-shard \
  --manifest "$MANIFEST" \
  --shard "$SHARD"
