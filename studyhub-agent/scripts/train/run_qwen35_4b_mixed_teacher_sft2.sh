#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export STUDYHUB_SFT2_DATASET_ID=qwen35_4b_sft2_mixed_teacher_retention_v2
export STUDYHUB_SFT2_EVIDENCE_PREFIX=qwen35-4b-sft2-mixed-v2
export STUDYHUB_SFT2_RUN_SLUG=qwen35-4b-sft2-mixed-v2
export STUDYHUB_SFT2_CONFIG="${PROJECT_ROOT}/configs/train/qwen35-4b-mixed-teacher-sft2.yaml"
export STUDYHUB_SFT2_PROGRAM="${PROJECT_ROOT}/configs/program-v4/sft2-mixed-teacher-retention-v2.json"
export STUDYHUB_SFT2_AUTHORIZATION="${PROJECT_ROOT}/configs/program-v4/qwen35-4b-sft2-mixed-v2-authorization.json"
export STUDYHUB_SFT2_EXPERIMENT=studyhub-qwen35-4b-mixed-teacher-sft2

exec "${PROJECT_ROOT}/scripts/train/run_qwen35_4b_sft2.sh" "$@"
