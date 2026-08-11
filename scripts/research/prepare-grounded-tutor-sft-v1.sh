#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_PYTHON="${STUDYHUB_BACKEND_PYTHON:-$ROOT_DIR/backend/.venv/bin/python}"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
ARTIFACT_DIR="$ROOT_DIR/training_artifacts/studyhub_agent_sft/grounded_tutor_9b_v1_0"
HOLDOUT_DIR="$ROOT_DIR/evaluation_artifacts/studyhub_agent/grounded_tutor_9b_holdout_v1"
TRANSCRIPTIONS="$ARTIFACT_DIR/evidence_extraction/qwen35_2b_preview_transcriptions.jsonl"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset ANTHROPIC_BASE_URL OPENAI_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-sft-preparation"
export PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

if [[ ! -f "$TRANSCRIPTIONS" ]]; then
  echo "preview transcriptions not found: $TRANSCRIPTIONS" >&2
  exit 2
fi

cd "$ROOT_DIR"
"$BACKEND_PYTHON" -m ml.agentic_platform.sft.build_grounded_tutor_9b_v1 \
  --transcriptions "$TRANSCRIPTIONS" \
  --output-dir "$ARTIFACT_DIR" \
  --holdout-dir "$HOLDOUT_DIR"
"$BACKEND_PYTHON" -m ml.agentic_platform.sft.export_llamafactory \
  --source "$ARTIFACT_DIR/grounded_tutor_9b_v1_0_trainval.jsonl" \
  --dataset-dir "$ARTIFACT_DIR/llamafactory" \
  --materials "$ROOT_DIR/backup/oss_materials/metadata/materials.jsonl" \
  --chunks "$ARTIFACT_DIR/clean_preview_chunks.jsonl" \
  --expected-count 1080 \
  --expected-train 960 \
  --expected-validation 120 \
  --expected-test 0 \
  --target-profile grounded_tutor_9b \
  --file-prefix grounded_tutor_9b \
  --dataset-name-prefix studyhub_grounded_tutor_9b
"$TRAIN_PYTHON" -m ml.agentic_platform.sft.inspect_tokenization \
  --model "$ROOT_DIR/models/P1/Qwen3.5-9B" \
  --dataset "$ARTIFACT_DIR/grounded_tutor_9b_v1_0_trainval.jsonl" \
  --report "$ARTIFACT_DIR/tokenization_report.json" \
  --cutoff-len 4096
"$BACKEND_PYTHON" -m ml.agentic_platform.sft.build_human_review_packet build \
  --dataset "$ARTIFACT_DIR/grounded_tutor_9b_v1_0_trainval.jsonl" \
  --output-dir "$ARTIFACT_DIR/human_review" \
  --split validation
