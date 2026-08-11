#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_PYTHON="${STUDYHUB_BACKEND_PYTHON:-$ROOT_DIR/backend/.venv/bin/python}"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
ARTIFACT_DIR="$ROOT_DIR/training_artifacts/studyhub_agent_sft/router_2b_v1_7_state_transitions"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset ANTHROPIC_BASE_URL OPENAI_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-sft-preparation"
export PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$ROOT_DIR"
"$BACKEND_PYTHON" -m ml.agentic_platform.sft.build_router_v1_7_state_transitions
"$BACKEND_PYTHON" -m ml.agentic_platform.sft.export_llamafactory \
  --source "$ARTIFACT_DIR/router_tool_2b_v1_7.jsonl" \
  --dataset-dir "$ARTIFACT_DIR/llamafactory" \
  --expected-count 1640 \
  --expected-train 1476 \
  --expected-validation 164 \
  --expected-test 0
"$TRAIN_PYTHON" -m ml.agentic_platform.sft.inspect_tokenization \
  --model "$ROOT_DIR/models/P0/Qwen3.5-2B" \
  --dataset "$ARTIFACT_DIR/router_tool_2b_v1_7.jsonl" \
  --report "$ARTIFACT_DIR/tokenization_report.json" \
  --cutoff-len 4096
"$BACKEND_PYTHON" -m ml.agentic_platform.sft.build_human_review_packet build \
  --dataset "$ARTIFACT_DIR/router_tool_2b_v1_7.jsonl" \
  --output-dir "$ARTIFACT_DIR/human_review" \
  --split validation
