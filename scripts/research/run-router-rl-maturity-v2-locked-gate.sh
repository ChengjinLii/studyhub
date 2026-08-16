#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
SPLIT="${1:?usage: $0 <test|sealed> [gpu-id]}"
GPU_ID="${2:-0}"
ARTIFACT_ROOT="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_rl_maturity_v2"
GATE_ROOT="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/gate"

if [[ "$SPLIT" != "test" && "$SPLIT" != "sealed" ]]; then
  echo "split must be test or sealed" >&2
  exit 2
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-maturity-v2-locked-gate"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

ARGS=(
  --split "$SPLIT"
  --model "$ROOT_DIR/training_artifacts/studyhub_agent_sft/qwen35_2b_router_v1_7_merged"
  --dataset "$ARTIFACT_ROOT/$SPLIT.jsonl"
  --frozen-manifest "$GATE_ROOT/frozen_candidate.json"
  --acceptance "$ROOT_DIR/ml/agentic_platform/rl/configs/router_rl_maturity_v2_acceptance.json"
  --output-root "$GATE_ROOT"
  --device cuda:0
)
if [[ "$SPLIT" == "sealed" ]]; then
  ARGS+=(--prior-test-gate "$GATE_ROOT/test_gate.json")
fi

cd "$ROOT_DIR"
CUDA_VISIBLE_DEVICES="$GPU_ID" PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
  -m ml.agentic_platform.rl.maturity_v2.locked_gate "${ARGS[@]}"
