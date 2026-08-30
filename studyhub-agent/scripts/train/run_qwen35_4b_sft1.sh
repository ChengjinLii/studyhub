#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-train"
RUNTIME_SHIM="${PROJECT_ROOT}/training/runtime_shims"
CONFIG="${PROJECT_ROOT}/configs/train/qwen35-4b-open-agentic-sft1.yaml"
PROGRAM="${PROJECT_ROOT}/configs/program-v4/qwen35-4b-agent-posttraining.json"
AUTHORIZATION="${PROJECT_ROOT}/configs/program-v4/qwen35-4b-sft1-authorization.json"
DATA_MANIFEST="${PROJECT_ROOT}/datasets/processed/open_agentic_sft_v2_qwen35_9b/manifest.json"
DATA_AUDIT="${PROJECT_ROOT}/docs/training/evidence/open-agentic-sft-v2-data-audit.json"
BENCHMARK_MANIFEST="${PROJECT_ROOT}/benchmarks/studyhub-agent-v2/manifest.json"
MODEL="${PROJECT_ROOT}/artifacts/areal/model-overlays/qwen35-4b-base-canonical-tokenizer"
MODEL_HASH_CACHE="${PROJECT_ROOT}/artifacts/areal/hash-cache/qwen35-4b-base.json"
MODE="${1:-smoke}"
SEED="${2:-20260827}"
GPUS="${STUDYHUB_TRAIN_GPUS:-0,1}"
MIN_FREE="${STUDYHUB_MIN_GPU_FREE_MIB:-76000}"
MAX_USED="${STUDYHUB_MAX_GPU_USED_MIB:-72000}"

if [[ "${MODE}" != "smoke" && "${MODE}" != "formal" ]]; then
  echo "Usage: $0 {smoke|formal} [seed]" >&2
  exit 2
fi
if [[ "${SEED}" != "20260827" ]]; then
  echo "4B SFT-1 is authorized only for seed 20260827." >&2
  exit 2
fi
if [[ "${STUDYHUB_ALLOW_TRAINING:-}" != "YES" || "${STUDYHUB_ALLOW_QWEN35_4B_SFT1:-}" != "YES" ]]; then
  echo "Set STUDYHUB_ALLOW_TRAINING=YES and STUDYHUB_ALLOW_QWEN35_4B_SFT1=YES." >&2
  exit 3
fi
if [[ -n "$(git -C "${PROJECT_ROOT}/.." status --porcelain)" ]]; then
  echo "4B SFT-1 requires a clean Git worktree." >&2
  exit 4
fi
if [[ ! -x "${VENV_DIR}/bin/areal" ]]; then
  echo "Missing pinned AReaL environment: ${VENV_DIR}" >&2
  exit 1
fi

readarray -t CONTRACT < <("${VENV_DIR}/bin/python" -S - "${AUTHORIZATION}" "${MODE}" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1]))
mode = sys.argv[2]
budget = value["budget"]
recipe = value["recipe"]
if mode == "smoke":
    print(budget["smoke_optimizer_updates"])
    print(budget["smoke_checkpoint_every_updates"])
    print(budget["smoke_maximum_wall_time_seconds"])
else:
    print(budget["planned_optimizer_updates"])
    print(budget["checkpoint_every_updates"])
    print(budget["maximum_wall_time_seconds"])
print(recipe["scheduler_total_steps"])
print(recipe["learning_rate"])
print(recipe["warmup_fraction"])
PY
)
PLANNED_UPDATES="${CONTRACT[0]}"
CHECKPOINT_UPDATES="${CONTRACT[1]}"
MAX_WALL_SECONDS="${CONTRACT[2]}"
SCHEDULER_TOTAL_STEPS="${CONTRACT[3]}"
BASE_LR="${CONTRACT[4]}"
WARMUP_FRACTION="${CONTRACT[5]}"

TRAINING_TRIAL="qwen35-4b-sft1-${MODE}-r32-seed-20260827"
EXPERIMENT="studyhub-qwen35-4b-open-agentic-sft1"
LOG_ROOT="${PROJECT_ROOT}/artifacts/areal/launcher_logs/qwen35-4b-sft1"
CHECKPOINT_ROOT="${PROJECT_ROOT}/artifacts/areal/checkpoints/$(id -un)/${EXPERIMENT}/${TRAINING_TRIAL}"
if [[ "${MODE}" == "smoke" ]]; then
  COMPLETION_MARKER="${CHECKPOINT_ROOT}/QWEN35_4B_SFT1_SMOKE_PASS.json"
else
  COMPLETION_MARKER="${CHECKPOINT_ROOT}/QWEN35_4B_SFT1_COMPLETE.json"
fi
SMOKE_MARKER="${PROJECT_ROOT}/artifacts/areal/checkpoints/$(id -un)/${EXPERIMENT}/qwen35-4b-sft1-smoke-r32-seed-20260827/QWEN35_4B_SFT1_SMOKE_PASS.json"
RECOVER_STEP_INFO="${CHECKPOINT_ROOT}/recover_info/step_info.json"

if [[ -f "${COMPLETION_MARKER}" ]]; then
  echo "4B SFT-1 ${MODE} is already complete: ${COMPLETION_MARKER}" >&2
  exit 5
fi

ATTEMPT_START_STEP="$("${VENV_DIR}/bin/python" -S - "${RECOVER_STEP_INFO}" "${PLANNED_UPDATES}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
planned = int(sys.argv[2])
if not path.is_file():
    print(0)
else:
    start = int(json.loads(path.read_text())["global_step"]) + 1
    if not 0 < start < planned:
        raise SystemExit(f"invalid recovery start step: {start}")
    print(start)
PY
)"

export PATH="${VENV_DIR}/bin:${PATH}"
unset PYTHONHOME ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy
export STUDYHUB_AREAL_CHAT_TEMPLATE_METADATA_BRIDGE=1
export STUDYHUB_AREAL_SCHEDULER_BRIDGE=1
export STUDYHUB_AREAL_SCHEDULER_TOTAL_STEPS="${SCHEDULER_TOTAL_STEPS}"
export STUDYHUB_TORCH_DETERMINISTIC_TRAINING=1
export CUBLAS_WORKSPACE_CONFIG=:4096:8
export NCCL_ALGO=Ring
export TORCH_COMPILE_DETERMINISTIC=1
if [[ "${ATTEMPT_START_STEP}" -gt 0 ]]; then
  export STUDYHUB_AREAL_RECOVER_SCHEDULER_STEP="${ATTEMPT_START_STEP}"
else
  unset STUDYHUB_AREAL_RECOVER_SCHEDULER_STEP || true
fi
export PYTHONPATH="${RUNTIME_SHIM}:${PROJECT_ROOT}:${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

PREFLIGHT_ARGS=(
  --mode "${MODE}"
  --config "${CONFIG}"
  --program "${PROGRAM}"
  --authorization "${AUTHORIZATION}"
  --gpus "${GPUS}"
  --min-free-mib "${MIN_FREE}"
)
if [[ "${MODE}" == "formal" ]]; then
  PREFLIGHT_ARGS+=(--smoke-marker "${SMOKE_MARKER}")
fi
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/preflight_qwen35_4b_sft1.py" "${PREFLIGHT_ARGS[@]}"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
ATTEMPT_ID="${TRAINING_TRIAL}-attempt-${TIMESTAMP}"
LOG_FILE="${LOG_ROOT}/${ATTEMPT_ID}.log"
GPU_CSV="${LOG_ROOT}/${ATTEMPT_ID}.gpu.csv"
RUN_METADATA="${LOG_ROOT}/${ATTEMPT_ID}.run.json"
RECOVERY_AUDIT_ROOT="${LOG_ROOT}/${ATTEMPT_ID}.recovery-audit"
LR_SEGMENT_INDEX="${CHECKPOINT_ROOT}/lr_schedule_segments.json"
LR_AUDIT="${CHECKPOINT_ROOT}/lr_schedule_audit.json"
SEGMENT_TEXT="${CHECKPOINT_ROOT}/lr_schedule_segments.txt"

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
METADATA_ARGS=()
for override in "${TRAIN_OVERRIDES[@]}"; do
  METADATA_ARGS+=(--override "${override}")
done
METADATA_ARGS+=(--override "studyhub_attempt_start_step=${ATTEMPT_START_STEP}")
METADATA_ARGS+=(--override "studyhub_scheduler_total_steps=${SCHEDULER_TOTAL_STEPS}")
mkdir -p "${LOG_ROOT}"

"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" start \
  --output "${RUN_METADATA}" \
  --project "${PROJECT_ROOT}" \
  --run-mode "qwen35-4b-sft1-${MODE}" \
  --config "${CONFIG}" \
  --dataset-manifest "${DATA_MANIFEST}" \
  --data-card "${DATA_AUDIT}" \
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
  --output "${RUN_METADATA}" --gpu-csv "${GPU_CSV}" --status "${STATUS}"

if ! "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/build_experiment_evidence.py" \
  --run-metadata "${RUN_METADATA}" --checkpoint-root "${CHECKPOINT_ROOT}" --evidence-tier CLAIM >/dev/null; then
  [[ "${STATUS}" -ne 0 ]] || STATUS=74
fi

if [[ "${STATUS}" -eq 0 ]]; then
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/collect_lr_audit_segments.py" \
    --log-root "${LOG_ROOT}" \
    --evidence-root "${PROJECT_ROOT}/artifacts/experiments" \
    --attempt-prefix "${TRAINING_TRIAL}" \
    --expected-updates "${PLANNED_UPDATES}" \
    --output "${LR_SEGMENT_INDEX}" >/dev/null || STATUS=76
fi

if [[ "${STATUS}" -eq 0 ]]; then
  "${VENV_DIR}/bin/python" -S - "${LR_SEGMENT_INDEX}" >"${SEGMENT_TEXT}" <<'PY' || STATUS=76
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("status") != "PASS":
    raise SystemExit("LR segment index did not pass")
for segment in payload.get("segments", []):
    print(f"{segment['metrics']},{segment['start_global_step']},{segment['count']}")
PY
fi

if [[ "${STATUS}" -eq 0 ]]; then
  readarray -t LR_SEGMENTS <"${SEGMENT_TEXT}"
  AUDIT_ARGS=()
  for segment in "${LR_SEGMENTS[@]}"; do
    AUDIT_ARGS+=(--segment "${segment}")
  done
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/audit_sft_lr_schedule.py" \
    "${AUDIT_ARGS[@]}" \
    --base-lr "${BASE_LR}" \
    --scheduler-total-steps "${SCHEDULER_TOTAL_STEPS}" \
    --warmup-fraction "${WARMUP_FRACTION}" \
    --expected-updates "${PLANNED_UPDATES}" \
    --output "${LR_AUDIT}" >/dev/null || STATUS=76
fi

if [[ "${STATUS}" -eq 0 ]]; then
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/record_open_agentic_sft_completion.py" \
    --mode "${MODE}" \
    --run-metadata "${RUN_METADATA}" \
    --checkpoint-root "${CHECKPOINT_ROOT}" \
    --authorization "${AUTHORIZATION}" \
    --lr-audit "${LR_AUDIT}" \
    --output "${COMPLETION_MARKER}" \
    --expected-updates "${PLANNED_UPDATES}" >/dev/null || STATUS=75
fi

tail -80 "${LOG_FILE}"
exit "${STATUS}"
