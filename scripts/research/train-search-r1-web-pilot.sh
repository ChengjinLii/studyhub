#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${STUDYHUB_ML_PYTHON:-$ROOT_DIR/../LLaMA-Factory/.venv/bin/python}"
BACKEND_SITE_PACKAGES="$($ROOT_DIR/backend/.venv/bin/python -c 'import site; print(site.getsitepackages()[0])')"
OUTPUT_DIR="${STUDYHUB_SEARCH_R1_OUTPUT_DIR:-$ROOT_DIR/training_artifacts/studyhub_agent_rl/web_search_r1_pilot_v1/seed_7703}"
EXTRA_ARGS=()
if [[ -n "${STUDYHUB_SEARCH_R1_EVAL_ONLY_SPLIT:-}" ]]; then
  EXTRA_ARGS+=(--eval-only-split "$STUDYHUB_SEARCH_R1_EVAL_ONLY_SPLIT")
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
unset STUDYHUB_WEB_ROUTER_EVAL_MODEL_BASE_URL
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONPATH="$BACKEND_SITE_PACKAGES:$ROOT_DIR/backend:$ROOT_DIR"

cd "$ROOT_DIR"
"$PYTHON" -m ml.agentic_platform.web_research.search_r1_grpo \
  --model "${STUDYHUB_SEARCH_R1_MODEL:-$ROOT_DIR/models/P0/Qwen3.5-2B}" \
  --sft-adapter "${STUDYHUB_SEARCH_R1_SFT_ADAPTER:-$ROOT_DIR/training_artifacts/studyhub_agent_sft/web_router_v1/qwen35_2b_lora_seed_7703}" \
  --output-dir "$OUTPUT_DIR" \
  --seed "${STUDYHUB_SEARCH_R1_SEED:-7703}" \
  --updates "${STUDYHUB_SEARCH_R1_UPDATES:-1}" \
  --group-size "${STUDYHUB_SEARCH_R1_GROUP_SIZE:-5}" \
  --max-turns "${STUDYHUB_SEARCH_R1_MAX_TURNS:-4}" \
  --max-new-tokens "${STUDYHUB_SEARCH_R1_MAX_NEW_TOKENS:-256}" \
  --temperature "${STUDYHUB_SEARCH_R1_TEMPERATURE:-1.0}" \
  --learning-rate "${STUDYHUB_SEARCH_R1_LEARNING_RATE:-5e-7}" \
  --clip-ratio "${STUDYHUB_SEARCH_R1_CLIP_RATIO:-0.2}" \
  --kl-loss-coef "${STUDYHUB_SEARCH_R1_KL_LOSS_COEF:-0.001}" \
  --device "${STUDYHUB_SEARCH_R1_DEVICE:-cuda}" \
  "${EXTRA_ARGS[@]}"
