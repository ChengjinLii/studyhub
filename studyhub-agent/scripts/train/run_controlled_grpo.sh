#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-train"
SIZE="${1:-}"
BRANCH="${2:-}"
MODE="${3:-check}"
SEED="${4:-6209}"
GPUS="${STUDYHUB_TRAIN_GPUS:-0,1}"

case "${SIZE}" in
  4b)
    CONFIG="${PROJECT_ROOT}/configs/train/open-grpo-qwen35-4b.yaml"
    BASE_MODEL="${PROJECT_ROOT}/../models/P1/Qwen3.5-4B"
    DEFAULT_MERGED="${PROJECT_ROOT}/artifacts/areal/merged-sft-qwen35-4b"
    ;;
  9b)
    CONFIG="${PROJECT_ROOT}/configs/train/open-grpo-qwen35-9b.yaml"
    BASE_MODEL="${PROJECT_ROOT}/../models/P1/Qwen3.5-9B"
    DEFAULT_MERGED="${PROJECT_ROOT}/artifacts/areal/merged-sft-qwen35-9b"
    ;;
  *) echo "Usage: $0 <4b|9b> <direct|sft> [check|gate|smoke|pilot|run] [seed]" >&2; exit 2 ;;
esac
case "${BRANCH}" in
  direct) MODEL="${BASE_MODEL}" ;;
  sft) MODEL="${STUDYHUB_SFT_MERGED_MODEL:-${DEFAULT_MERGED}}" ;;
  *) echo "Usage: $0 <4b|9b> <direct|sft> [check|gate|smoke|pilot|run] [seed]" >&2; exit 2 ;;
esac
case "${MODE}" in
  check|gate|smoke|pilot|run) ;;
  *) echo "Usage: $0 <4b|9b> <direct|sft> [check|gate|smoke|pilot|run] [seed]" >&2; exit 2 ;;
esac

if [[ ! -x "${VENV_DIR}/bin/areal" ]]; then
  echo "Missing AReaL environment. Run scripts/train/setup_areal_env.sh rl first." >&2
  exit 1
fi

PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}" \
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/preflight_controlled_experiment.py"

if [[ "${BRANCH}" == "sft" && ! -f "${MODEL}/studyhub_merged_manifest.json" ]]; then
  if [[ "${MODE}" == "check" ]]; then
    printf 'GRPO %s SFT-initialized branch is scripted; its merged checkpoint is created only after SFT.\n' "${SIZE}"
    printf 'Expected future checkpoint: %s\n' "${MODEL}"
    printf 'No training was started.\n'
    exit 0
  fi
  echo "Missing merged SFT checkpoint: ${MODEL}" >&2
  echo "Run merge_sft_lora.py after SFT, or set STUDYHUB_SFT_MERGED_MODEL." >&2
  exit 1
fi

if [[ "${MODE}" == "check" ]]; then
  printf 'GRPO %s/%s is ready. No training was started.\n' "${SIZE}" "${BRANCH}"
  printf 'To run a pilot explicitly: STUDYHUB_ALLOW_TRAINING=YES %s %s %s pilot %s\n' "$0" "${SIZE}" "${BRANCH}" "${SEED}"
  exit 0
fi
if [[ "${STUDYHUB_ALLOW_TRAINING:-}" != "YES" ]]; then
  echo "Refusing to train. Set STUDYHUB_ALLOW_TRAINING=YES for gate/smoke/pilot/run." >&2
  exit 3
fi

MIN_FREE="${STUDYHUB_MIN_GPU_FREE_MIB:-76000}"
MAX_USED="${STUDYHUB_MAX_GPU_USED_MIB:-68000}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
TRIAL="${BRANCH}-${MODE}-seed-${SEED}-${TIMESTAMP}"
LOG_ROOT="${PROJECT_ROOT}/artifacts/areal/launcher_logs/grpo-${SIZE}"
REWARD_ROOT="${PROJECT_ROOT}/artifacts/areal/reward-v2/${SIZE}/${TRIAL}"
LOG_FILE="${LOG_ROOT}/${TRIAL}.log"
GPU_CSV="${LOG_ROOT}/${TRIAL}.gpu.csv"
RUN_METADATA="${LOG_ROOT}/${TRIAL}.run.json"
DATASET="${PROJECT_ROOT}/datasets/processed/open_agent_rl_v1/manifest.json"
OVERRIDES=(
  "seed=${SEED}"
  "trial_name=${TRIAL}"
  "actor.path=${MODEL}"
  "experiment_name=studyhub-open-grpo-${SIZE}-${BRANCH}"
  "reward_artifact_root=${REWARD_ROOT}"
)
case "${MODE}" in
  gate) OVERRIDES+=("total_train_steps=1" "saver.freq_steps=1" "recover.mode=disabled") ;;
  smoke) OVERRIDES+=("total_train_steps=10" "saver.freq_steps=5" "recover.mode=disabled") ;;
  pilot) OVERRIDES+=("total_train_steps=25" "saver.freq_steps=5" "recover.mode=disabled") ;;
esac

mkdir -p "${LOG_ROOT}"
METADATA_ARGS=()
for override in "${OVERRIDES[@]}"; do
  METADATA_ARGS+=(--override "${override}")
done
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" start \
  --output "${RUN_METADATA}" \
  --project "${PROJECT_ROOT}" \
  --run-mode "grpo-${SIZE}-${BRANCH}-${MODE}" \
  --config "${CONFIG}" \
  --dataset-manifest "${DATASET}" \
  --model "${MODEL}" \
  --areal-lock "${PROJECT_ROOT}/training/areal/upstream.lock.json" \
  --gpu "${GPUS}" \
  --max-used-mib "${MAX_USED}" \
  --min-free-mib "${MIN_FREE}" \
  --log-file "${LOG_FILE}" \
  --gpu-csv "${GPU_CSV}" \
  "${METADATA_ARGS[@]}"

unset ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy
export CUDA_VISIBLE_DEVICES="${GPUS}"
export WANDB_MODE=disabled
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export PYTORCH_ALLOC_CONF=expandable_segments:True

set +e
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/guarded_gpu_launch.py" \
  --gpus "${GPUS}" \
  --min-free-mib "${MIN_FREE}" \
  --max-used-mib "${MAX_USED}" \
  --log "${LOG_FILE}" \
  --gpu-csv "${GPU_CSV}" \
  -- "${VENV_DIR}/bin/areal" train run \
  --config "${CONFIG}" \
  --driver training.rl.open_agent_driver:main \
  "${OVERRIDES[@]}"
STATUS=$?
set -e

"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" finish \
  --output "${RUN_METADATA}" \
  --gpu-csv "${GPU_CSV}" \
  --status "${STATUS}"
tail -80 "${LOG_FILE}"
exit "${STATUS}"
