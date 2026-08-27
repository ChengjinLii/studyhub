#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-train"
RUNTIME_SHIM="${PROJECT_ROOT}/training/runtime_shims"
CONFIG="${PROJECT_ROOT}/configs/train/runtime-sft-v3-qwen35-9b.yaml"
DATA_MANIFEST="${PROJECT_ROOT}/datasets/processed/runtime_sft_v3_qwen35_9b/manifest.json"
DATA_CARD="${PROJECT_ROOT}/configs/program-v3/runtime-sft-v3-data-card.json"
MODEL="${PROJECT_ROOT}/../models/P1/Qwen3.5-9B"
MODE="${1:-check}"
SEED="${2:-20260827}"
GPUS="${STUDYHUB_TRAIN_GPUS:-0,1}"
MIN_FREE="${STUDYHUB_MIN_GPU_FREE_MIB:-76000}"
MAX_USED="${STUDYHUB_MAX_GPU_USED_MIB:-72000}"

case "${MODE}" in
  check|gate|profile-r16|profile-r32|run) ;;
  *) echo "Usage: $0 [check|gate|profile-r16|profile-r32|run] [seed]" >&2; exit 2 ;;
esac
if [[ ! -x "${VENV_DIR}/bin/areal" ]]; then
  echo "Missing pinned AReaL environment: ${VENV_DIR}" >&2
  exit 1
fi

export PATH="${VENV_DIR}/bin:${PATH}"
unset PYTHONHOME
export STUDYHUB_AREAL_CHAT_TEMPLATE_METADATA_BRIDGE=1
export PYTHONPATH="${RUNTIME_SHIM}:${PROJECT_ROOT}:${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
unset ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy

PREFLIGHT_ARGS=(--config "${CONFIG}" --data-card "${DATA_CARD}")
if [[ "${MODE}" != "check" ]]; then
  PREFLIGHT_ARGS+=(--gpus "${GPUS}" --min-free-mib "${MIN_FREE}")
fi
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/preflight_runtime_sft_v3.py" "${PREFLIGHT_ARGS[@]}"

if [[ "${MODE}" == "check" ]]; then
  printf 'Runtime SFT v3 is ready. No GPU process was started.\n'
  exit 0
fi
if [[ "${STUDYHUB_ALLOW_TRAINING:-}" != "YES" ]]; then
  echo "Refusing to start an optimizer. Set STUDYHUB_ALLOW_TRAINING=YES." >&2
  exit 3
fi
if [[ "${MODE}" == "run" ]]; then
  if [[ "${STUDYHUB_ALLOW_FORMAL_SFT:-}" != "YES" ]]; then
    echo "Formal SFT requires STUDYHUB_ALLOW_FORMAL_SFT=YES." >&2
    exit 3
  fi
  if [[ -n "$(git -C "${PROJECT_ROOT}/.." status --porcelain)" && "${STUDYHUB_ALLOW_DIRTY_FORMAL:-}" != "YES" ]]; then
    echo "Formal SFT requires a clean Git worktree." >&2
    exit 4
  fi
fi

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
TRIAL="${MODE}-seed-${SEED}-${TIMESTAMP}"
LOG_ROOT="${PROJECT_ROOT}/artifacts/areal/launcher_logs/runtime-sft-v3-9b"
LOG_FILE="${LOG_ROOT}/${TRIAL}.log"
GPU_CSV="${LOG_ROOT}/${TRIAL}.gpu.csv"
RUN_METADATA="${LOG_ROOT}/${TRIAL}.run.json"
MODEL_HASH_CACHE="${PROJECT_ROOT}/artifacts/areal/hash-cache/qwen35-9b.json"
EXPERIMENT="studyhub-runtime-sft-v3-9b"
CHECKPOINT_ROOT="${PROJECT_ROOT}/artifacts/areal/checkpoints/$(id -un)/${EXPERIMENT}/${TRIAL}"
OVERRIDES=("seed=${SEED}" "trial_name=${TRIAL}")

case "${MODE}" in
  gate)
    OVERRIDES+=(
      "total_train_steps=1"
      "saver.freq_steps=1"
      "evaluator.freq_steps=null"
      "recover.mode=disabled"
      "actor.optimizer.warmup_steps_proportion=0.0"
    )
    ;;
  profile-r16)
    OVERRIDES+=(
      "total_train_steps=5"
      "actor.lora_rank=16"
      "actor.lora_alpha=16"
      "saver.freq_steps=5"
      "evaluator.freq_steps=null"
      "recover.mode=disabled"
      "actor.optimizer.warmup_steps_proportion=0.0"
    )
    ;;
  profile-r32)
    OVERRIDES+=(
      "total_train_steps=5"
      "actor.lora_rank=32"
      "actor.lora_alpha=32"
      "saver.freq_steps=5"
      "evaluator.freq_steps=null"
      "recover.mode=disabled"
      "actor.optimizer.warmup_steps_proportion=0.0"
    )
    ;;
esac

mkdir -p "${LOG_ROOT}"
METADATA_ARGS=()
for override in "${OVERRIDES[@]}"; do
  METADATA_ARGS+=(--override "${override}")
done
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" start \
  --output "${RUN_METADATA}" \
  --project "${PROJECT_ROOT}" \
  --run-mode "runtime-sft-v3-9b-${MODE}" \
  --config "${CONFIG}" \
  --dataset-manifest "${DATA_MANIFEST}" \
  --data-card "${DATA_CARD}" \
  --model "${MODEL}" \
  --model-hash-cache "${MODEL_HASH_CACHE}" \
  --areal-lock "${PROJECT_ROOT}/training/areal/upstream.lock.json" \
  --hermes-lock "${PROJECT_ROOT}/integrations/hermes/upstream.lock.json" \
  --gpu "${GPUS}" \
  --max-used-mib "${MAX_USED}" \
  --min-free-mib "${MIN_FREE}" \
  --log-file "${LOG_FILE}" \
  --gpu-csv "${GPU_CSV}" \
  "${METADATA_ARGS[@]}"

export CUDA_VISIBLE_DEVICES="${GPUS}"
export WANDB_MODE=disabled
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
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
  --driver training.sft.open_bootstrap_driver:main \
  "${OVERRIDES[@]}"
STATUS=$?
set -e

"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" finish \
  --output "${RUN_METADATA}" \
  --gpu-csv "${GPU_CSV}" \
  --status "${STATUS}"

EVIDENCE_TIER="DIAGNOSTIC"
if [[ "${MODE}" == "run" ]]; then
  EVIDENCE_TIER="CLAIM"
fi
if ! "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/build_experiment_evidence.py" \
  --run-metadata "${RUN_METADATA}" \
  --checkpoint-root "${CHECKPOINT_ROOT}" \
  --evidence-tier "${EVIDENCE_TIER}" >/dev/null; then
  echo "Failed to finalize evidence for ${TRIAL}." >&2
  [[ "${STATUS}" -ne 0 ]] || STATUS=74
fi

tail -80 "${LOG_FILE}"
exit "${STATUS}"
