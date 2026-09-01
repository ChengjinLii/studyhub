#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT_ROOT="${STUDYHUB_EVAL_ARTIFACT_ROOT:-${PROJECT_ROOT}}"
VENV_DIR="${STUDYHUB_TRAIN_VENV:-${ARTIFACT_ROOT}/.venv-train}"
MODEL="${STUDYHUB_SFT1_MERGED_MODEL:-${ARTIFACT_ROOT}/artifacts/areal/merged/qwen35-4b-sft1-r32-seed-20260827}"
OUTPUT_ROOT="${STUDYHUB_PROTOCOL_OUTPUT_ROOT:-${ARTIFACT_ROOT}/artifacts/protocol-holdout/qwen35-4b-sft1}"
CHECKPOINT_ROOT="${ARTIFACT_ROOT}/artifacts/areal/checkpoints/$(id -un)/studyhub-qwen35-4b-open-agentic-sft1/qwen35-4b-sft1-formal-r32-seed-20260827"
COMPLETION_MARKER="${CHECKPOINT_ROOT}/QWEN35_4B_SFT1_COMPLETE.json"
GPUS="${STUDYHUB_EVAL_GPUS:-0,1}"
MAX_ROWS="${STUDYHUB_PROTOCOL_MAX_ROWS:-0}"
MIN_FREE="${STUDYHUB_MIN_GPU_FREE_MIB:-70000}"
MAX_USED="${STUDYHUB_MAX_GPU_USED_MIB:-76000}"
MAX_WALL="${STUDYHUB_PROTOCOL_MAX_WALL_SECONDS:-14400}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_ROOT="${ARTIFACT_ROOT}/artifacts/areal/launcher_logs/qwen35-4b-sft1-protocol"
LOG_FILE="${LOG_ROOT}/protocol-${TIMESTAMP}.log"
GPU_CSV="${LOG_ROOT}/protocol-${TIMESTAMP}.gpu.csv"

if [[ -n "$(git -C "${PROJECT_ROOT}/.." status --porcelain)" ]]; then
  echo "M1 protocol evaluation requires a clean Git worktree." >&2
  exit 4
fi
if [[ ! -f "${COMPLETION_MARKER}" ]]; then
  echo "M1 completion marker is missing: ${COMPLETION_MARKER}" >&2
  exit 5
fi
if [[ ! -f "${MODEL}/studyhub_merged_manifest.json" ]]; then
  echo "Merged M1 checkpoint is missing: ${MODEL}" >&2
  exit 6
fi
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Pinned training environment is missing: ${VENV_DIR}" >&2
  exit 7
fi

mkdir -p "${LOG_ROOT}"
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/guarded_gpu_launch.py" \
  --gpus "${GPUS}" \
  --min-free-mib "${MIN_FREE}" \
  --max-used-mib "${MAX_USED}" \
  --max-wall-seconds "${MAX_WALL}" \
  --interrupt-grace-seconds 120 \
  --log "${LOG_FILE}" \
  --gpu-csv "${GPU_CSV}" \
  -- "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/evaluate_qwen35_4b_protocol_holdout.py" \
    --artifact-root "${ARTIFACT_ROOT}" \
    --python "${VENV_DIR}/bin/python" \
    --model "${MODEL}" \
    --output-root "${OUTPUT_ROOT}" \
    --gpus "${GPUS}" \
    --max-rows "${MAX_ROWS}"
