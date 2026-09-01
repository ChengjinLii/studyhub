#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export STUDYHUB_SFT2_ARTIFACT_ROOT=/data/chengjin/studyhub/studyhub-agent
export STUDYHUB_TRAIN_VENV=/data/chengjin/studyhub/studyhub-agent/.venv-train
export STUDYHUB_SFT2_DATASET_ID=qwen35_4b_sft2_compact_mixed_v1
export STUDYHUB_SFT2_EVIDENCE_PREFIX=qwen35-4b-sft2-compact-v1
export STUDYHUB_SFT2_RUN_SLUG=qwen35-4b-sft2-compact-v1
export STUDYHUB_SFT2_CONFIG="${PROJECT_ROOT}/configs/train/qwen35-4b-compact-sft2.yaml"
export STUDYHUB_SFT2_PROGRAM="${PROJECT_ROOT}/configs/program-v4/sft2-compact-mixed-v1.json"
export STUDYHUB_SFT2_AUTHORIZATION="${PROJECT_ROOT}/configs/program-v4/qwen35-4b-sft2-compact-v1-authorization.json"
export STUDYHUB_SFT2_EXPERIMENT=studyhub-qwen35-4b-compact-sft2

exec "${PROJECT_ROOT}/scripts/train/run_qwen35_4b_sft2.sh" "$@"
