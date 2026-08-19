#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
COMMAND="${1:?usage: $0 <evaluate|summarize> [shard] [gpu-id]}"
SHARD="${2:-0}"
GPU_ID="${3:-$SHARD}"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-maturity-v2-sweep-evaluation"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT_DIR"
case "$COMMAND" in
  evaluate)
    if [[ "$SHARD" != "0" && "$SHARD" != "1" ]]; then
      echo "shard must be 0 or 1" >&2
      exit 2
    fi
    CUDA_VISIBLE_DEVICES="$GPU_ID" PYTHONPATH="$WORKSPACE_ROOT/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
      -m ml.agentic_platform.rl.maturity_v2.sweep_evaluate evaluate-shard \
      --shard "$SHARD" \
      --device cuda:0
    ;;
  summarize)
    PYTHONPATH="$WORKSPACE_ROOT/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
      -m ml.agentic_platform.rl.maturity_v2.sweep_evaluate summarize
    ;;
  *)
    echo "command must be evaluate or summarize" >&2
    exit 2
    ;;
esac
