#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT_ROOT="${STUDYHUB_SFT2_ARTIFACT_ROOT:-${PROJECT_ROOT}}"
PYTHON_BIN="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/studyhub/studyhub-agent/.venv-train/bin/python}"
TOKENIZER_MODEL="${STUDYHUB_SFT2_TOKENIZER_MODEL:-/data/chengjin/studyhub/studyhub-agent/artifacts/areal/model-overlays/qwen35-4b-base-canonical-tokenizer}"
SEMANTIC_MODEL="${STUDYHUB_SFT2_SEMANTIC_MODEL:-/data/chengjin/studyhub/models/P0/bge-m3}"
SEMANTIC_DEVICE="${STUDYHUB_SFT2_SEMANTIC_DEVICE:-cuda:0}"
TEACHER_DATA="${STUDYHUB_SFT2_TEACHER_DATA:-${ARTIFACT_ROOT}/datasets/interim/codex_hermes_teacher_v1/accepted.jsonl}"
RETENTION_DATA="${STUDYHUB_SFT2_RETENTION_DATA:-${ARTIFACT_ROOT}/datasets/interim/open_agentic_sft_v2/selected.jsonl}"
DATASET_ID="${STUDYHUB_SFT2_DATASET_ID:-qwen35_4b_sft2_codex_retention_v1}"
EVIDENCE_PREFIX="${STUDYHUB_SFT2_EVIDENCE_PREFIX:-qwen35-4b-sft2}"
PROGRAM="${STUDYHUB_SFT2_PROGRAM:-${PROJECT_ROOT}/configs/program-v4/sft2-codex-retention-v1.json}"
INTERIM="${ARTIFACT_ROOT}/datasets/interim/${DATASET_ID}"
PROCESSED="${ARTIFACT_ROOT}/datasets/processed/${DATASET_ID}"
EVIDENCE="${ARTIFACT_ROOT}/docs/training/evidence"

CANDIDATES="${INTERIM}/candidates.jsonl"
CANDIDATE_BLOCKLIST="${INTERIM}/candidate-semantic-blocklist.jsonl"
CANDIDATE_SEMANTIC="${EVIDENCE}/${EVIDENCE_PREFIX}-candidate-semantic-dedup.json"
SELECTED="${INTERIM}/selected.jsonl"
SELECTED_SEMANTIC="${EVIDENCE}/${EVIDENCE_PREFIX}-selected-semantic-dedup.json"

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

"${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/data/build_qwen35_4b_sft2_candidates.py" \
  --teacher "${TEACHER_DATA}" \
  --retention "${RETENTION_DATA}" \
  --program "${PROGRAM}" \
  --model "${TOKENIZER_MODEL}" \
  --output "${CANDIDATES}" \
  --teacher-audit-output "${EVIDENCE}/${EVIDENCE_PREFIX}-teacher-input-audit.json"

"${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/data/audit_open_agentic_semantic_dedup.py" \
  --input "${CANDIDATES}" \
  --model "${SEMANTIC_MODEL}" \
  --device "${SEMANTIC_DEVICE}" \
  --output "${CANDIDATE_SEMANTIC}" \
  --blocklist-output "${CANDIDATE_BLOCKLIST}"

"${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/data/select_open_agentic_token_budget.py" \
  --program "${PROGRAM}" \
  --candidate "${CANDIDATES}" \
  --model "${TOKENIZER_MODEL}" \
  --output "${SELECTED}" \
  --processed-output "${PROCESSED}" \
  --inventory-cache "${INTERIM}/token-inventory.jsonl" \
  --semantic-blocklist "${CANDIDATE_BLOCKLIST}" \
  --semantic-evidence "${CANDIDATE_SEMANTIC}"

"${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/data/audit_open_agentic_semantic_dedup.py" \
  --input "${SELECTED}" \
  --model "${SEMANTIC_MODEL}" \
  --device "${SEMANTIC_DEVICE}" \
  --output "${SELECTED_SEMANTIC}"

"${PYTHON_BIN}" "${PROJECT_ROOT}/scripts/data/audit_open_agentic_sft_v2.py" \
  --program "${PROGRAM}" \
  --selected "${SELECTED}" \
  --processed "${PROCESSED}" \
  --model "${TOKENIZER_MODEL}" \
  --semantic-evidence "${SELECTED_SEMANTIC}" \
  --evidence "${EVIDENCE}/${EVIDENCE_PREFIX}-data-audit.json" \
  --data-card "${ARTIFACT_ROOT}/docs/training/${EVIDENCE_PREFIX^^}_DATA_CARD.md"
