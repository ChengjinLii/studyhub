#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
GPU_ID="${STUDYHUB_EVIDENCE_GPU:-0}"
BATCH_SIZE="${STUDYHUB_EVIDENCE_BATCH_SIZE:-4}"
MAX_NEW_TOKENS="${STUDYHUB_EVIDENCE_MAX_NEW_TOKENS:-1024}"

if [[ ! -x "$PYTHON" ]]; then
  echo "training Python not executable: $PYTHON" >&2
  exit 2
fi

GPU_USED_MIB="$(
  nvidia-smi -i "$GPU_ID" --query-gpu=memory.used --format=csv,noheader,nounits \
    | tr -d ' '
)"
if (( GPU_USED_MIB > 1024 )); then
  echo "GPU $GPU_ID is not idle (${GPU_USED_MIB} MiB used); refusing to interfere" >&2
  exit 3
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset ANTHROPIC_BASE_URL OPENAI_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-sft-evidence-extraction"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTHONPATH="$WORKSPACE_ROOT/backend:$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

cd "$ROOT_DIR"
CUDA_VISIBLE_DEVICES="$GPU_ID" "$PYTHON" \
  -m ml.agentic_platform.sft.extract_preview_evidence \
  --device cuda:0 \
  --batch-size "$BATCH_SIZE" \
  --max-new-tokens "$MAX_NEW_TOKENS" \
  --retry-errors
