#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-train"
RUNTIME_SHIM="${PROJECT_ROOT}/training/runtime_shims"
CONFIG="${PROJECT_ROOT}/configs/train/open-only-sft-v1.1-qwen35-9b.yaml"
PROGRAM="${PROJECT_ROOT}/configs/program-v3/open-only-sft-v1.1-lrmatched.json"
AUTHORIZATION="${PROJECT_ROOT}/configs/program-v3/open-only-sft-v1.1-lrmatched-authorization.json"
DATA_MANIFEST="${PROJECT_ROOT}/datasets/processed/open_only_sft_v1_qwen35_9b/manifest.json"
DATA_CARD="${PROJECT_ROOT}/configs/program-v3/open-only-sft-v1-data-card.json"
BENCHMARK_MANIFEST="${PROJECT_ROOT}/benchmarks/studyhub-agent-v2/manifest.json"
MODEL="${PROJECT_ROOT}/../models/P1/Qwen3.5-9B"
MODEL_HASH_CACHE="${PROJECT_ROOT}/artifacts/areal/hash-cache/qwen35-9b.json"
SEED="${1:-20260827}"
GPUS="${STUDYHUB_TRAIN_GPUS:-0,1}"
MIN_FREE="${STUDYHUB_MIN_GPU_FREE_MIB:-76000}"
MAX_USED="${STUDYHUB_MAX_GPU_USED_MIB:-72000}"

if [[ "${SEED}" != "20260827" ]]; then
  echo "The corrected Open-Only run is authorized only for seed 20260827." >&2
  exit 2
fi
if [[ "${STUDYHUB_ALLOW_TRAINING:-}" != "YES" || "${STUDYHUB_ALLOW_OPEN_ONLY_SFT_V1_1:-}" != "YES" ]]; then
  echo "Set STUDYHUB_ALLOW_TRAINING=YES and STUDYHUB_ALLOW_OPEN_ONLY_SFT_V1_1=YES." >&2
  exit 3
fi
if [[ -n "$(git -C "${PROJECT_ROOT}/.." status --porcelain)" ]]; then
  echo "The corrected Open-Only run requires a clean Git worktree." >&2
  exit 4
fi
if [[ ! -x "${VENV_DIR}/bin/areal" ]]; then
  echo "Missing pinned AReaL environment: ${VENV_DIR}" >&2
  exit 1
fi

readarray -t CONTRACT < <("${VENV_DIR}/bin/python" -S - "${AUTHORIZATION}" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
b=d["budget"]
r=d["recipe"]
print(b["planned_optimizer_updates"])
print(b["checkpoint_every_updates"])
print(b["maximum_wall_time_seconds"])
print(r["scheduler_total_steps"])
print(r["learning_rate"])
print(r["warmup_fraction"])
PY
)
PLANNED_UPDATES="${CONTRACT[0]}"
CHECKPOINT_UPDATES="${CONTRACT[1]}"
MAX_WALL_SECONDS="${CONTRACT[2]}"
SCHEDULER_TOTAL_STEPS="${CONTRACT[3]}"
BASE_LR="${CONTRACT[4]}"
WARMUP_FRACTION="${CONTRACT[5]}"

TRAINING_TRIAL="open-only-sft-v1-1-lrmatched-r16-seed-20260827"
EXPERIMENT="studyhub-open-only-sft-v1-1-9b"
LOG_ROOT="${PROJECT_ROOT}/artifacts/areal/launcher_logs/open-only-sft-v1-1-9b"
CHECKPOINT_ROOT="${PROJECT_ROOT}/artifacts/areal/checkpoints/$(id -un)/${EXPERIMENT}/${TRAINING_TRIAL}"
COMPLETION_MARKER="${CHECKPOINT_ROOT}/OPEN_ONLY_SFT_V1_1_COMPLETE.json"
RECOVER_STEP_INFO="${CHECKPOINT_ROOT}/recover_info/step_info.json"
LR_SEGMENT_INDEX="${CHECKPOINT_ROOT}/lr_schedule_segments.json"
LR_AUDIT="${CHECKPOINT_ROOT}/lr_schedule_audit.json"

if [[ -f "${COMPLETION_MARKER}" ]]; then
  echo "The corrected Open-Only run is already complete: ${COMPLETION_MARKER}" >&2
  exit 5
fi

ATTEMPT_START_STEP="$("${VENV_DIR}/bin/python" -S - "${RECOVER_STEP_INFO}" "${PLANNED_UPDATES}" <<'PY'
import json, pathlib, sys
path=pathlib.Path(sys.argv[1])
planned=int(sys.argv[2])
if not path.is_file():
    print(0)
else:
    value=json.loads(path.read_text())
    start=int(value["global_step"])+1
    if int(value["steps_per_epoch"]) != planned:
        raise SystemExit(f"recovery steps_per_epoch drift: {value['steps_per_epoch']} != {planned}")
    if not 0 < start < planned:
        raise SystemExit(f"invalid recovery start step: {start}")
    print(start)
PY
)"
if [[ ! "${ATTEMPT_START_STEP}" =~ ^[0-9]+$ ]]; then
  echo "Recovery start step is not a non-negative integer: ${ATTEMPT_START_STEP}" >&2
  exit 64
fi

export PATH="${VENV_DIR}/bin:${PATH}"
unset PYTHONHOME ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy
export STUDYHUB_AREAL_CHAT_TEMPLATE_METADATA_BRIDGE=1
export STUDYHUB_AREAL_SCHEDULER_BRIDGE=1
export STUDYHUB_AREAL_SCHEDULER_TOTAL_STEPS="${SCHEDULER_TOTAL_STEPS}"
if [[ "${ATTEMPT_START_STEP}" -gt 0 ]]; then
  export STUDYHUB_AREAL_RECOVER_SCHEDULER_STEP="${ATTEMPT_START_STEP}"
else
  unset STUDYHUB_AREAL_RECOVER_SCHEDULER_STEP || true
fi
export PYTHONPATH="${RUNTIME_SHIM}:${PROJECT_ROOT}:${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/preflight_open_only_sft_v1.py" \
  --config "${CONFIG}" \
  --program "${PROGRAM}" \
  --authorization "${AUTHORIZATION}" \
  --data-card "${DATA_CARD}" \
  --gpus "${GPUS}" \
  --min-free-mib "${MIN_FREE}"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
ATTEMPT_ID="${TRAINING_TRIAL}-attempt-${TIMESTAMP}"
LOG_FILE="${LOG_ROOT}/${ATTEMPT_ID}.log"
GPU_CSV="${LOG_ROOT}/${ATTEMPT_ID}.gpu.csv"
RUN_METADATA="${LOG_ROOT}/${ATTEMPT_ID}.run.json"
RECOVERY_AUDIT_ROOT="${LOG_ROOT}/${ATTEMPT_ID}.recovery-audit"

export STUDYHUB_AREAL_RECOVERY_STATE_BRIDGE=1
export STUDYHUB_RECOVERY_AUDIT_ROOT="${RECOVERY_AUDIT_ROOT}"
export STUDYHUB_RECOVERY_AUDIT_START_STEP="${ATTEMPT_START_STEP}"

TRAIN_OVERRIDES=(
  "seed=${SEED}"
  "trial_name=${TRAINING_TRIAL}"
  "total_train_steps=${PLANNED_UPDATES}"
  "saver.freq_steps=${CHECKPOINT_UPDATES}"
  "saver.freq_secs=null"
  "recover.freq_steps=${CHECKPOINT_UPDATES}"
  "recover.freq_secs=null"
  "evaluator.freq_steps=null"
  "evaluator.freq_secs=null"
)
METADATA_OVERRIDES=(
  "${TRAIN_OVERRIDES[@]}"
  "studyhub_attempt_start_step=${ATTEMPT_START_STEP}"
  "studyhub_scheduler_total_steps=${SCHEDULER_TOTAL_STEPS}"
  "studyhub_recover_scheduler_step=${ATTEMPT_START_STEP}"
)
METADATA_ARGS=()
for override in "${METADATA_OVERRIDES[@]}"; do
  METADATA_ARGS+=(--override "${override}")
done
mkdir -p "${LOG_ROOT}"
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" start \
  --output "${RUN_METADATA}" \
  --project "${PROJECT_ROOT}" \
  --run-mode "open-only-sft-v1-1-9b-lrmatched" \
  --config "${CONFIG}" \
  --dataset-manifest "${DATA_MANIFEST}" \
  --data-card "${DATA_CARD}" \
  --benchmark-manifest "${BENCHMARK_MANIFEST}" \
  --authorization "${AUTHORIZATION}" \
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
export WANDB_MODE=disabled HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export PYTORCH_ALLOC_CONF=expandable_segments:True

set +e
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/guarded_gpu_launch.py" \
  --gpus "${GPUS}" \
  --min-free-mib "${MIN_FREE}" \
  --max-used-mib "${MAX_USED}" \
  --max-wall-seconds "${MAX_WALL_SECONDS}" \
  --interrupt-grace-seconds 180 \
  --log "${LOG_FILE}" \
  --gpu-csv "${GPU_CSV}" \
  -- "${VENV_DIR}/bin/areal" train run \
  --config "${CONFIG}" \
  --driver training.sft.open_bootstrap_driver:main \
  "${TRAIN_OVERRIDES[@]}"
STATUS=$?
set -e

"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" finish \
  --output "${RUN_METADATA}" \
  --gpu-csv "${GPU_CSV}" \
  --status "${STATUS}"

if ! "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/build_experiment_evidence.py" \
  --run-metadata "${RUN_METADATA}" \
  --checkpoint-root "${CHECKPOINT_ROOT}" \
  --evidence-tier CLAIM >/dev/null; then
  echo "Failed to finalize corrected Open-Only evidence for ${ATTEMPT_ID}." >&2
  [[ "${STATUS}" -ne 0 ]] || STATUS=74
fi

if [[ "${STATUS}" -eq 0 ]]; then
  SEGMENT_TEXT="${CHECKPOINT_ROOT}/lr_schedule_segments.txt"
  if ! "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/collect_lr_audit_segments.py" \
    --log-root "${LOG_ROOT}" \
    --evidence-root "${PROJECT_ROOT}/artifacts/experiments" \
    --attempt-prefix "${TRAINING_TRIAL}" \
    --expected-updates "${PLANNED_UPDATES}" \
    --output "${LR_SEGMENT_INDEX}" >"${SEGMENT_TEXT}"; then
    echo "Failed to collect a complete LR segment index." >&2
    STATUS=76
  fi
fi

if [[ "${STATUS}" -eq 0 ]]; then
  readarray -t LR_SEGMENTS <"${SEGMENT_TEXT}"
  AUDIT_ARGS=()
  for segment in "${LR_SEGMENTS[@]}"; do
    AUDIT_ARGS+=(--segment "${segment}")
  done
  if ! "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/audit_sft_lr_schedule.py" \
    "${AUDIT_ARGS[@]}" \
    --base-lr "${BASE_LR}" \
    --scheduler-total-steps "${SCHEDULER_TOTAL_STEPS}" \
    --warmup-fraction "${WARMUP_FRACTION}" \
    --expected-updates "${PLANNED_UPDATES}" \
    --output "${LR_AUDIT}" >/dev/null; then
    echo "The corrected Open-Only LR trajectory failed its exact audit." >&2
    STATUS=76
  fi
fi

if [[ "${STATUS}" -eq 0 ]]; then
  if ! "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/record_open_only_sft_completion.py" \
    --run-metadata "${RUN_METADATA}" \
    --checkpoint-root "${CHECKPOINT_ROOT}" \
    --authorization "${AUTHORIZATION}" \
    --lr-audit "${LR_AUDIT}" \
    --output "${COMPLETION_MARKER}" \
    --expected-updates "${PLANNED_UPDATES}" >/dev/null; then
    echo "The run exited zero but failed the corrected Open-Only completion contract." >&2
    STATUS=75
  fi
fi

tail -80 "${LOG_FILE}"
exit "${STATUS}"
