#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT_ROOT="${STUDYHUB_EVAL_ARTIFACT_ROOT:-${PROJECT_ROOT}}"

if [[ -n "$(git -C "${PROJECT_ROOT}/.." status --porcelain)" ]]; then
  echo "Qwen3.5-4B evaluation requires a clean Git worktree." >&2
  exit 4
fi

export STUDYHUB_EVAL_ARTIFACT_ROOT="${ARTIFACT_ROOT}"
export STUDYHUB_EVAL_MODEL="${STUDYHUB_EVAL_MODEL:-${ARTIFACT_ROOT}/artifacts/areal/model-overlays/qwen35-4b-base-canonical-tokenizer}"
export STUDYHUB_EVAL_MODEL_ROLE="${STUDYHUB_EVAL_MODEL_ROLE:-m0-base}"
export STUDYHUB_EVAL_MODEL_RUN_PREFIX="${STUDYHUB_EVAL_MODEL_RUN_PREFIX:-qwen35-4b-base}"

exec bash "${PROJECT_ROOT}/scripts/benchmark/run_9b_model_eval_v2.sh" "$@"
