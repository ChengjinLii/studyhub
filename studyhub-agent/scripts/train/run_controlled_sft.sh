#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-train"
SIZE="${1:-}"
MODE="${2:-check}"
SEED="${3:-6209}"
GPU="${STUDYHUB_TRAIN_GPU:-0}"

case "${SIZE}" in
  4b)
    CONFIG="${PROJECT_ROOT}/configs/train/open-sft-qwen35-4b.yaml"
    MODEL="${PROJECT_ROOT}/../models/P1/Qwen3.5-4B"
    DATASET="${PROJECT_ROOT}/datasets/processed/open_sft_bootstrap_v2_qwen35_4b/manifest.json"
    DEFAULT_MAX_USED=50000
    ;;
  9b)
    CONFIG="${PROJECT_ROOT}/configs/train/open-sft-qwen35-9b.yaml"
    MODEL="${PROJECT_ROOT}/../models/P1/Qwen3.5-9B"
    DATASET="${PROJECT_ROOT}/datasets/processed/open_sft_bootstrap_v2_qwen35_9b/manifest.json"
    DEFAULT_MAX_USED=65000
    ;;
  *) echo "Usage: $0 <4b|9b> [check|gate|run] [seed]" >&2; exit 2 ;;
esac
case "${MODE}" in
  check|gate|run) ;;
  *) echo "Usage: $0 <4b|9b> [check|gate|run] [seed]" >&2; exit 2 ;;
esac

if [[ ! -x "${VENV_DIR}/bin/areal" ]]; then
  echo "Missing AReaL environment. Run scripts/train/setup_areal_env.sh rl first." >&2
  exit 1
fi

PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}" \
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/preflight_controlled_experiment.py"

if [[ "${MODE}" == "check" ]]; then
  printf 'SFT %s is ready. No training was started.\n' "${SIZE}"
  printf 'To train explicitly: STUDYHUB_ALLOW_TRAINING=YES %s %s run %s\n' "$0" "${SIZE}" "${SEED}"
  exit 0
fi
if [[ "${STUDYHUB_ALLOW_TRAINING:-}" != "YES" ]]; then
  echo "Refusing to train. Set STUDYHUB_ALLOW_TRAINING=YES for gate/run." >&2
  exit 3
fi

MIN_FREE="${STUDYHUB_MIN_GPU_FREE_MIB:-76000}"
MAX_USED="${STUDYHUB_MAX_GPU_USED_MIB:-${DEFAULT_MAX_USED}}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
TRIAL="${MODE}-seed-${SEED}-${TIMESTAMP}"
LOG_ROOT="${PROJECT_ROOT}/artifacts/areal/launcher_logs/sft-${SIZE}"
LOG_FILE="${LOG_ROOT}/${TRIAL}.log"
GPU_CSV="${LOG_ROOT}/${TRIAL}.gpu.csv"
RUN_METADATA="${LOG_ROOT}/${TRIAL}.run.json"
OVERRIDES=("seed=${SEED}" "trial_name=${TRIAL}")
if [[ "${MODE}" == "gate" ]]; then
  OVERRIDES+=("total_train_steps=1" "saver.freq_steps=1" "recover.mode=disabled")
fi

mkdir -p "${LOG_ROOT}"
METADATA_ARGS=()
for override in "${OVERRIDES[@]}"; do
  METADATA_ARGS+=(--override "${override}")
done
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" start \
  --output "${RUN_METADATA}" \
  --project "${PROJECT_ROOT}" \
  --run-mode "sft-${SIZE}-${MODE}" \
  --config "${CONFIG}" \
  --dataset-manifest "${DATASET}" \
  --model "${MODEL}" \
  --areal-lock "${PROJECT_ROOT}/training/areal/upstream.lock.json" \
  --gpu "${GPU}" \
  --max-used-mib "${MAX_USED}" \
  --min-free-mib "${MIN_FREE}" \
  --log-file "${LOG_FILE}" \
  --gpu-csv "${GPU_CSV}" \
  "${METADATA_ARGS[@]}"

unset ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy
export CUDA_VISIBLE_DEVICES="${GPU}"
export WANDB_MODE=disabled
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export PYTORCH_ALLOC_CONF=expandable_segments:True

set +e
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/guarded_gpu_launch.py" \
  --gpus "${GPU}" \
  --min-free-mib "${MIN_FREE}" \
  --max-used-mib "${MAX_USED}" \
  --log "${LOG_FILE}" \
  --gpu-csv "${GPU_CSV}" \
  -- "${VENV_DIR}/bin/areal" train run \
  --config "${CONFIG}" \
  --driver training.sft.open_bootstrap_driver:main \
  "${OVERRIDES[@]}"
STATUS=$?
set -e

"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" finish \
  --output "${RUN_METADATA}" \
  --gpu-csv "${GPU_CSV}" \
  --status "${STATUS}"
tail -80 "${LOG_FILE}"
exit "${STATUS}"
