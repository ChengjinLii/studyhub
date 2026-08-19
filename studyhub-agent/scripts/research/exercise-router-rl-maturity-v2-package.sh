#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
GPU_ID="${1:-0}"
ARTIFACT_ROOT="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_rl_maturity_v2"
GATE_ROOT="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/gate"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-maturity-v2-package"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT_DIR"
CUDA_VISIBLE_DEVICES="$GPU_ID" PYTHONPATH="$WORKSPACE_ROOT/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
  -m ml.agentic_platform.rl.maturity_v2.offline_package \
  --repo-root "$ROOT_DIR" \
  --model "$ROOT_DIR/training_artifacts/studyhub_agent_sft/qwen35_2b_router_v1_7_merged" \
  --frozen-manifest "$GATE_ROOT/frozen_candidate.json" \
  --validation "$ARTIFACT_ROOT/validation.jsonl" \
  --output-dir "$ARTIFACT_ROOT/offline_package" \
  --device cuda:0
