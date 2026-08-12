#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
COMMAND="${1:?usage: $0 <prepare|run|evaluate|summarize> [shard] [gpu-id]}"
SHARD="${2:-0}"
GPU_ID="${3:-$SHARD}"
ARTIFACT_ROOT="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_rl_maturity_v2"
SWEEP_ROOT="$ARTIFACT_ROOT/experiments/grpo_stability_sweep"
EVAL_ROOT="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation/grpo_stability_sweep"
PRIMARY_RESULTS="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation/grpo_sweep/sweep_results.json"
FAILED_SCALE_RESULTS="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation/grpo_scale_sweep/scale_sweep_results.json"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-maturity-v2-stability-sweep"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT_DIR"
case "$COMMAND" in
  prepare)
    PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
      -m ml.agentic_platform.rl.maturity_v2.stability_sweep prepare \
      --primary-results "$PRIMARY_RESULTS" \
      --failed-scale-results "$FAILED_SCALE_RESULTS" \
      --output-dir "$SWEEP_ROOT"
    ;;
  run)
    CUDA_VISIBLE_DEVICES="$GPU_ID" PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
      -m ml.agentic_platform.rl.maturity_v2.stability_sweep run-shard \
      --manifest "$SWEEP_ROOT/sweep_manifest.json" \
      --shard "$SHARD"
    ;;
  evaluate)
    CUDA_VISIBLE_DEVICES="$GPU_ID" PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
      -m ml.agentic_platform.rl.maturity_v2.stability_sweep evaluate-shard \
      --manifest "$SWEEP_ROOT/sweep_manifest.json" \
      --evaluation-root "$EVAL_ROOT" \
      --shard "$SHARD" \
      --device cuda:0
    ;;
  summarize)
    PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
      -m ml.agentic_platform.rl.maturity_v2.stability_sweep summarize \
      --manifest "$SWEEP_ROOT/sweep_manifest.json" \
      --evaluation-root "$EVAL_ROOT"
    ;;
  *)
    echo "unknown command: $COMMAND" >&2
    exit 2
    ;;
esac
