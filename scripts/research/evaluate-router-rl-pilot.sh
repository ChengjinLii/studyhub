#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
GPU_ID="${STUDYHUB_RL_GPU:-1}"
SPLIT="${1:-validation}"
LABEL="${2:?usage: evaluate-router-rl-pilot.sh SPLIT LABEL ADAPTER}"
ADAPTER="${3:?usage: evaluate-router-rl-pilot.sh SPLIT LABEL ADAPTER}"
MODEL="$ROOT_DIR/models/P0/Qwen3.5-2B"
DATASET="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_grpo_pilot_v1/states.jsonl"
OUTPUT="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_pilot_v1/$SPLIT/$LABEL"

if [[ "$SPLIT" != "validation" && "$SPLIT" != "test" ]]; then
  echo "split must be validation or test" >&2
  exit 2
fi
if [[ ! -f "$ADAPTER/adapter_model.safetensors" ]]; then
  echo "adapter is incomplete: $ADAPTER" >&2
  exit 2
fi
if [[ -e "$OUTPUT/summary.json" ]]; then
  echo "evaluation output already exists: $OUTPUT" >&2
  exit 4
fi
GPU_USED_MIB="$(nvidia-smi -i "$GPU_ID" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')"
if (( GPU_USED_MIB > 1024 )); then
  echo "GPU $GPU_ID is not idle (${GPU_USED_MIB} MiB used); refusing to interfere" >&2
  exit 3
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-evaluation"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

cd "$ROOT_DIR"
CUDA_VISIBLE_DEVICES="$GPU_ID" PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$TRAIN_PYTHON" \
  -m ml.agentic_platform.rl.evaluate \
  --model "$MODEL" \
  --adapter "$ADAPTER" \
  --dataset "$DATASET" \
  --split "$SPLIT" \
  --output-dir "$OUTPUT" \
  --batch-size 6 \
  --max-new-tokens 320
