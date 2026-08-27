#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export STUDYHUB_EVAL_MODEL="${STUDYHUB_EVAL_MODEL:-${PROJECT_ROOT}/../models/P1/Qwen3.5-9B}"
export STUDYHUB_EVAL_MODEL_ROLE="${STUDYHUB_EVAL_MODEL_ROLE:-base}"
exec "${PROJECT_ROOT}/scripts/benchmark/run_9b_model_eval_v2.sh" "$@"
