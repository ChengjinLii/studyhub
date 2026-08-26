#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-train"
RUNTIME_SHIM="${PROJECT_ROOT}/training/runtime_shims"
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
  check|gate|smoke|pilot|run|eval) ;;
  *) echo "Usage: $0 <4b|9b> <direct|sft> [check|gate|smoke|pilot|run|eval] [seed]" >&2; exit 2 ;;
esac

MODEL="${STUDYHUB_GRPO_MODEL:-${MODEL}}"
MODEL_LABEL="${STUDYHUB_MODEL_LABEL:-${BRANCH}}"
if [[ ! "${MODEL_LABEL}" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "STUDYHUB_MODEL_LABEL must contain only lowercase letters, digits, and hyphens." >&2
  exit 2
fi

if [[ ! -x "${VENV_DIR}/bin/areal" ]]; then
  echo "Missing AReaL environment. Run scripts/train/setup_areal_env.sh rl first." >&2
  exit 1
fi

# SGLang is spawned by AReaL through `python3`; force the pinned 3.12 venv so
# its interpreter and standard library cannot be mixed with the caller's Conda.
export PATH="${VENV_DIR}/bin:${PATH}"
unset PYTHONHOME
export STUDYHUB_DISABLE_DEEP_GEMM_WITHOUT_NVCC=1
export STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC=1
export STUDYHUB_AREAL_ADMIN_API_KEY="$(${VENV_DIR}/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))')"

PYTHONPATH="${RUNTIME_SHIM}:${PROJECT_ROOT}:${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}" \
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/preflight_controlled_experiment.py"

if [[ "${BRANCH}" == "sft" && -z "${STUDYHUB_GRPO_MODEL:-}" && ! -f "${MODEL}/studyhub_merged_manifest.json" ]]; then
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
  echo "Refusing to launch. Set STUDYHUB_ALLOW_TRAINING=YES for gate/smoke/pilot/run/eval." >&2
  exit 3
fi

SGLANG_MODEL="${PROJECT_ROOT}/artifacts/areal/model-overlays/${SIZE}-${MODEL_LABEL}"
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/prepare_sglang_model_overlay.py" \
  --model "${MODEL}" \
  --output "${SGLANG_MODEL}"

MIN_FREE="${STUDYHUB_MIN_GPU_FREE_MIB:-76000}"
MAX_USED="${STUDYHUB_MAX_GPU_USED_MIB:-68000}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
TRIAL="${MODEL_LABEL}-${MODE}-seed-${SEED}-${TIMESTAMP}"
LOG_ROOT="${PROJECT_ROOT}/artifacts/areal/launcher_logs/grpo-${SIZE}"
REWARD_ROOT="${PROJECT_ROOT}/artifacts/areal/reward-v2/${SIZE}/${TRIAL}"
LOG_FILE="${LOG_ROOT}/${TRIAL}.log"
GPU_CSV="${LOG_ROOT}/${TRIAL}.gpu.csv"
RUN_METADATA="${LOG_ROOT}/${TRIAL}.run.json"
DATASET="${PROJECT_ROOT}/datasets/processed/open_agent_rl_v1/manifest.json"
EXPERIMENT="studyhub-open-grpo-${SIZE}-${BRANCH}"
if [[ "${MODE}" == "eval" ]]; then
  DATASET="${PROJECT_ROOT}/datasets/processed/open_agent_rl_dev_eval32_v1/manifest.json"
  EXPERIMENT="studyhub-open-grpo-${SIZE}-evaluation"
fi

redact_admin_key() {
  STUDYHUB_SECRET_TO_REDACT="${STUDYHUB_AREAL_ADMIN_API_KEY:-}" \
    "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/redact_trial_secret.py" \
      --artifacts-root "${PROJECT_ROOT}/artifacts/areal" \
      --trial "${TRIAL}" \
      --summary "${LOG_ROOT}/${TRIAL}.redaction.json" >/dev/null 2>&1 || true
}
trap redact_admin_key EXIT

OVERRIDES=(
  "seed=${SEED}"
  "trial_name=${TRIAL}"
  "actor.path=${MODEL}"
  "sglang.model_path=${SGLANG_MODEL}"
  "experiment_name=${EXPERIMENT}"
  "reward_artifact_root=${REWARD_ROOT}"
)
case "${MODE}" in
  gate) OVERRIDES+=("total_train_steps=1" "saver.freq_steps=1" "recover.mode=disabled" "actor.optimizer.warmup_steps_proportion=0.0") ;;
  smoke) OVERRIDES+=("total_train_steps=10" "saver.freq_steps=5" "recover.mode=disabled" "actor.optimizer.warmup_steps_proportion=0.0") ;;
  pilot) OVERRIDES+=("total_train_steps=25" "saver.freq_steps=5" "recover.mode=disabled" "actor.optimizer.warmup_steps_proportion=0.0") ;;
  eval) OVERRIDES+=(
    "total_train_steps=1"
    "saver.freq_steps=1"
    "recover.mode=disabled"
    "actor.optimizer.lr=0.0"
    "actor.optimizer.warmup_steps_proportion=0.0"
    "valid_dataset.path=${PROJECT_ROOT}/datasets/processed/open_agent_rl_dev_eval32_v1/hf_dataset"
    "evaluator.freq_epochs=null"
    "evaluator.freq_steps=1"
  ) ;;
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
  --hermes-lock "${PROJECT_ROOT}/integrations/hermes/upstream.lock.json" \
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
export PYTHONPATH="${RUNTIME_SHIM}:${PROJECT_ROOT}:${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
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

redact_admin_key
unset STUDYHUB_AREAL_ADMIN_API_KEY
trap - EXIT

"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" finish \
  --output "${RUN_METADATA}" \
  --gpu-csv "${GPU_CSV}" \
  --status "${STATUS}"
CHECKPOINT_ROOT="${PROJECT_ROOT}/artifacts/areal/checkpoints/chengjin/${EXPERIMENT}/${TRIAL}"
TRAJECTORY_ROOT="${PROJECT_ROOT}/artifacts/areal/logs/chengjin/${EXPERIMENT}/${TRIAL}/rollout"
EVIDENCE_REWARD_ROOT="${REWARD_ROOT}"
EVIDENCE_TASK_ROOT="${PROJECT_ROOT}/datasets/processed/open_agent_rl_v1/tasks"
if [[ "${MODE}" == "eval" ]]; then
  TRAJECTORY_ROOT="${PROJECT_ROOT}/artifacts/areal/logs/chengjin/${EXPERIMENT}/${TRIAL}/eval-rollout"
  EVIDENCE_REWARD_ROOT="${REWARD_ROOT}/validation"
  EVIDENCE_TASK_ROOT="${PROJECT_ROOT}/datasets/processed/open_agent_rl_dev_eval32_v1/tasks.jsonl"
fi
EVIDENCE_TIER="DIAGNOSTIC"
if [[ "${MODE}" == "run" ]]; then
  EVIDENCE_TIER="CLAIM"
fi
if ! "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/build_experiment_evidence.py" \
  --run-metadata "${RUN_METADATA}" \
  --reward-root "${EVIDENCE_REWARD_ROOT}" \
  --checkpoint-root "${CHECKPOINT_ROOT}" \
  --trajectory-root "${TRAJECTORY_ROOT}" \
  --task-root "${EVIDENCE_TASK_ROOT}" \
  --max-sequence-tokens 4096 \
  --evidence-tier "${EVIDENCE_TIER}" >/dev/null; then
  echo "Failed to finalize the evidence bundle for ${TRIAL}." >&2
  if [[ "${STATUS}" -eq 0 ]]; then
    STATUS=74
    "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" finish \
      --output "${RUN_METADATA}" \
      --gpu-csv "${GPU_CSV}" \
      --status "${STATUS}"
  fi
fi
tail -80 "${LOG_FILE}"
exit "${STATUS}"
