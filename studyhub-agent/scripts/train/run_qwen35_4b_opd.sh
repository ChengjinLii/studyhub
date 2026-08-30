#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-train"
RUNTIME_SHIM="${PROJECT_ROOT}/training/runtime_shims"
CONFIG="${PROJECT_ROOT}/configs/train/qwen35-4b-strict-opd.yaml"
PROGRAM="${PROJECT_ROOT}/configs/program-v4/qwen35-4b-opd-v1.json"
AUTHORIZATION="${PROJECT_ROOT}/configs/program-v4/qwen35-4b-opd-v1-authorization.json"
LR_SELECTION="${PROJECT_ROOT}/docs/training/evidence/qwen35-4b-opd-lr-selection.json"
MODE="${1:-}"
SEED="${2:-20260827}"
GPUS="${STUDYHUB_TRAIN_GPUS:-0,1}"
MIN_FREE="${STUDYHUB_MIN_GPU_FREE_MIB:-76000}"
MAX_USED="${STUDYHUB_MAX_GPU_USED_MIB:-79000}"

case "${MODE}" in
  lr1e6) LEARNING_RATE="1e-6"; UPDATES=16; BATCH_SIZE=2; CHECKPOINT_EVERY=16 ;;
  lr3e6) LEARNING_RATE="3e-6"; UPDATES=16; BATCH_SIZE=2; CHECKPOINT_EVERY=16 ;;
  pilot) UPDATES=64; BATCH_SIZE=4; CHECKPOINT_EVERY=16 ;;
  formal) UPDATES=300; BATCH_SIZE=8; CHECKPOINT_EVERY=50 ;;
  *) echo "Usage: $0 {lr1e6|lr3e6|pilot|formal} [seed]" >&2; exit 2 ;;
esac
if [[ "${SEED}" != "20260827" ]]; then
  echo "Strict OPD is authorized only for seed 20260827." >&2
  exit 2
fi
if [[ "${STUDYHUB_ALLOW_TRAINING:-}" != "YES" || "${STUDYHUB_ALLOW_QWEN35_4B_OPD:-}" != "YES" ]]; then
  echo "Set STUDYHUB_ALLOW_TRAINING=YES and STUDYHUB_ALLOW_QWEN35_4B_OPD=YES." >&2
  exit 3
fi
if [[ -n "$(git -C "${PROJECT_ROOT}/.." status --porcelain)" ]]; then
  echo "Strict OPD requires a clean Git worktree." >&2
  exit 4
fi
if [[ ! -x "${VENV_DIR}/bin/areal" || ! -f "${AUTHORIZATION}" ]]; then
  echo "Missing pinned AReaL environment or OPD authorization." >&2
  exit 1
fi

if [[ "${MODE}" == "pilot" || "${MODE}" == "formal" ]]; then
  if [[ ! -f "${LR_SELECTION}" ]]; then
    echo "Missing frozen OPD LR selection: ${LR_SELECTION}" >&2
    exit 5
  fi
  LEARNING_RATE="$(${VENV_DIR}/bin/python -S - "${LR_SELECTION}" <<'PY'
import json
import sys
value=json.load(open(sys.argv[1]))
if value.get("status") != "PASS_OPD_LR_SELECTION":
    raise SystemExit("OPD LR selection is not passing")
print(value["selected_learning_rate"])
PY
)"
fi

EXPERIMENT="studyhub-qwen35-4b-strict-opd"
TRIAL="qwen35-4b-opd-${MODE}-seed-20260827"
LOG_ROOT="${PROJECT_ROOT}/artifacts/areal/launcher_logs/qwen35-4b-opd"
CHECKPOINT_ROOT="${PROJECT_ROOT}/artifacts/areal/checkpoints/$(id -un)/${EXPERIMENT}/${TRIAL}"
REWARD_ROOT="${PROJECT_ROOT}/artifacts/areal/strict-opd/rewards/${TRIAL}"
ATTEMPT_ID="${TRIAL}-attempt-$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_ROOT}/${ATTEMPT_ID}.log"
GPU_CSV="${LOG_ROOT}/${ATTEMPT_ID}.gpu.csv"
RUN_METADATA="${LOG_ROOT}/${TRIAL}.run.json"
DATA_MANIFEST="${PROJECT_ROOT}/datasets/processed/opd_prompt_pool_v1/manifest.json"
PILOT_MARKER="${PROJECT_ROOT}/artifacts/areal/checkpoints/$(id -un)/${EXPERIMENT}/qwen35-4b-opd-pilot-seed-20260827/QWEN35_4B_OPD_PILOT_PASS.json"
case "${MODE}" in
  lr1e6) STAGE_MARKER="${CHECKPOINT_ROOT}/QWEN35_4B_OPD_LR1E6_PASS.json" ;;
  lr3e6) STAGE_MARKER="${CHECKPOINT_ROOT}/QWEN35_4B_OPD_LR3E6_PASS.json" ;;
  pilot) STAGE_MARKER="${CHECKPOINT_ROOT}/QWEN35_4B_OPD_PILOT_PASS.json" ;;
  formal) STAGE_MARKER="${CHECKPOINT_ROOT}/QWEN35_4B_OPD_COMPLETE.json" ;;
esac
if [[ -f "${STAGE_MARKER}" ]]; then
  echo "OPD ${MODE} already complete: ${STAGE_MARKER}" >&2
  exit 5
fi

export PATH="${VENV_DIR}/bin:${PATH}"
unset PYTHONHOME ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy
export STUDYHUB_DISABLE_DEEP_GEMM_WITHOUT_NVCC=1
export STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC=1
export STUDYHUB_AREAL_CHAT_TEMPLATE_METADATA_BRIDGE=1
export STUDYHUB_AREAL_OPD_BRIDGE=1
export STUDYHUB_OPD_STUDENT_ADAPTER="$(${VENV_DIR}/bin/python -S - "${AUTHORIZATION}" <<'PY'
import json
import pathlib
import sys
print(pathlib.Path(json.load(open(sys.argv[1]))["lineage"]["m2_adapter_path"]).resolve())
PY
)"
export STUDYHUB_AREAL_ADMIN_API_KEY="$(${VENV_DIR}/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export PYTHONPATH="${RUNTIME_SHIM}:${PROJECT_ROOT}:${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

PREFLIGHT_ARGS=(
  --mode "${MODE}"
  --config "${CONFIG}"
  --program "${PROGRAM}"
  --authorization "${AUTHORIZATION}"
  --learning-rate "${LEARNING_RATE}"
  --updates "${UPDATES}"
  --batch-size "${BATCH_SIZE}"
  --gpus "${GPUS}"
  --min-free-mib "${MIN_FREE}"
)
if [[ "${MODE}" == "pilot" || "${MODE}" == "formal" ]]; then
  PREFLIGHT_ARGS+=(--lr-selection "${LR_SELECTION}")
fi
if [[ "${MODE}" == "formal" ]]; then
  PREFLIGHT_ARGS+=(--pilot-marker "${PILOT_MARKER}")
fi
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/preflight_qwen35_4b_opd.py" "${PREFLIGHT_ARGS[@]}"

OVERRIDES=(
  "seed=${SEED}"
  "trial_name=${TRIAL}"
  "experiment_name=${EXPERIMENT}"
  "total_train_steps=${UPDATES}"
  "actor.optimizer.lr=${LEARNING_RATE}"
  "train_dataset.batch_size=${BATCH_SIZE}"
  "rollout.consumer_batch_size=${BATCH_SIZE}"
  "saver.freq_steps=${CHECKPOINT_EVERY}"
  "reward_artifact_root=${REWARD_ROOT}"
  "evaluator.freq_steps=null"
  "evaluator.freq_secs=null"
)
if [[ "${MODE}" == "formal" ]]; then
  OVERRIDES+=("recover.mode=auto" "recover.freq_steps=50" "recover.freq_secs=null")
else
  OVERRIDES+=("recover.mode=disabled" "recover.freq_steps=null" "recover.freq_secs=null")
fi

mkdir -p "${LOG_ROOT}"
METADATA_ARGS=()
for override in "${OVERRIDES[@]}"; do
  METADATA_ARGS+=(--override "${override}")
done
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" start \
  --output "${RUN_METADATA}" \
  --project "${PROJECT_ROOT}" \
  --run-mode "qwen35-4b-strict-opd-${MODE}" \
  --config "${CONFIG}" \
  --dataset-manifest "${DATA_MANIFEST}" \
  --benchmark-manifest "${PROJECT_ROOT}/benchmarks/studyhub-agent-v2/manifest.json" \
  --authorization "${AUTHORIZATION}" \
  --model "${PROJECT_ROOT}/artifacts/areal/model-overlays/qwen35-4b-base-canonical-tokenizer" \
  --model-hash-cache "${PROJECT_ROOT}/artifacts/areal/hash-cache/qwen35-4b-base.json" \
  --areal-lock "${PROJECT_ROOT}/training/areal/upstream.lock.json" \
  --hermes-lock "${PROJECT_ROOT}/integrations/hermes/upstream.lock.json" \
  --gpu "${GPUS}" \
  --max-used-mib "${MAX_USED}" \
  --min-free-mib "${MIN_FREE}" \
  --log-file "${LOG_FILE}" \
  --gpu-csv "${GPU_CSV}" \
  "${METADATA_ARGS[@]}"

redact_admin_key() {
  STUDYHUB_SECRET_TO_REDACT="${STUDYHUB_AREAL_ADMIN_API_KEY:-}" \
    "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/redact_trial_secret.py" \
      --artifacts-root "${PROJECT_ROOT}/artifacts/areal" \
      --trial "${TRIAL}" \
      --summary "${LOG_ROOT}/${TRIAL}.redaction.json" >/dev/null 2>&1 || true
}
trap redact_admin_key EXIT

export CUDA_VISIBLE_DEVICES="${GPUS}"
export WANDB_MODE=disabled HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export PYTORCH_ALLOC_CONF=expandable_segments:True
set +e
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/guarded_gpu_launch.py" \
  --gpus "${GPUS}" \
  --min-free-mib "${MIN_FREE}" \
  --max-used-mib "${MAX_USED}" \
  --max-wall-seconds 28800 \
  --interrupt-grace-seconds 180 \
  --log "${LOG_FILE}" \
  --gpu-csv "${GPU_CSV}" \
  -- "${VENV_DIR}/bin/areal" train run \
  --config "${CONFIG}" \
  --driver training.opd.driver:main \
  "${OVERRIDES[@]}"
STATUS=$?
set -e

redact_admin_key
unset STUDYHUB_AREAL_ADMIN_API_KEY
trap - EXIT
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" finish \
  --output "${RUN_METADATA}" --gpu-csv "${GPU_CSV}" --status "${STATUS}"

TRAJECTORY_ROOT="${PROJECT_ROOT}/artifacts/areal/logs/$(id -un)/${EXPERIMENT}/${TRIAL}/rollout"
EVIDENCE_TIER="DIAGNOSTIC"
[[ "${MODE}" == "formal" ]] && EVIDENCE_TIER="CLAIM"
if ! "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/build_experiment_evidence.py" \
  --run-metadata "${RUN_METADATA}" \
  --reward-root "${REWARD_ROOT}" \
  --checkpoint-root "${CHECKPOINT_ROOT}" \
  --trajectory-root "${TRAJECTORY_ROOT}" \
  --task-root "${PROJECT_ROOT}/datasets/processed/opd_prompt_pool_v1/tasks" \
  --max-sequence-tokens 16384 \
  --evidence-tier "${EVIDENCE_TIER}" >/dev/null; then
  [[ "${STATUS}" -ne 0 ]] || STATUS=74
fi

TRAINER_METRICS="${PROJECT_ROOT}/artifacts/experiments/${TRIAL}/metrics/trainer.json"
if [[ "${STATUS}" -eq 0 ]]; then
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/record_qwen35_4b_opd_stage.py" \
    --mode "${MODE}" \
    --trainer-metrics "${TRAINER_METRICS}" \
    --reward-root "${REWARD_ROOT}" \
    --checkpoint-root "${CHECKPOINT_ROOT}" \
    --authorization "${AUTHORIZATION}" \
    --learning-rate "${LEARNING_RATE}" \
    --expected-updates "${UPDATES}" \
    --output "${STAGE_MARKER}" >/dev/null || STATUS=75
fi

tail -80 "${LOG_FILE}"
exit "${STATUS}"
