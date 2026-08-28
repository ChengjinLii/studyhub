#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-train"
RUNTIME_SHIM="${PROJECT_ROOT}/training/runtime_shims"
CONFIG="${PROJECT_ROOT}/configs/train/open-only-sft-v1.1-qwen35-9b.yaml"
PROGRAM="${PROJECT_ROOT}/configs/program-v3/open-only-sft-v1.1-lrmatched.json"
AUTHORIZATION="${PROJECT_ROOT}/configs/program-v3/open-only-sft-v1.1-lrmatched-authorization.json"
EQUIVALENCE_CONTRACT="${PROJECT_ROOT}/configs/program-v3/sft-recovery-numerical-equivalence-v1.json"
DATA_MANIFEST="${PROJECT_ROOT}/datasets/processed/open_only_sft_v1_qwen35_9b/manifest.json"
DATA_CARD="${PROJECT_ROOT}/configs/program-v3/open-only-sft-v1-data-card.json"
BENCHMARK_MANIFEST="${PROJECT_ROOT}/benchmarks/studyhub-agent-v2/manifest.json"
MODEL="${PROJECT_ROOT}/../models/P1/Qwen3.5-9B"
MODEL_HASH_CACHE="${PROJECT_ROOT}/artifacts/areal/hash-cache/qwen35-9b.json"
SEED=20260827
GPUS="${STUDYHUB_TRAIN_GPUS:-0,1}"
MIN_FREE="${STUDYHUB_MIN_GPU_FREE_MIB:-76000}"
MAX_USED="${STUDYHUB_MAX_GPU_USED_MIB:-72000}"
SCHEDULER_TOTAL_STEPS=5456
BASE_LR=2e-5
WARMUP_FRACTION=0.03
PROFILE="${STUDYHUB_RECOVERY_GATE_PROFILE:-early-warmup}"
case "${PROFILE}" in
  early-warmup)
    PREFIX_GLOBAL_STEP=1
    EXPECTED_UPDATES=4
    GATE_SCOPE="EARLY_WARMUP_MECHANICS_ONLY"
    ;;
  post-warmup)
    PREFIX_GLOBAL_STEP=164
    EXPECTED_UPDATES=167
    GATE_SCOPE="POST_WARMUP_CONFIRMATION"
    ;;
  cadence-210)
    PREFIX_GLOBAL_STEP=209
    EXPECTED_UPDATES=212
    GATE_SCOPE="RECOVERY_CADENCE_CONFIRMATION"
    ;;
  *)
    echo "Unknown recovery Gate profile: ${PROFILE}" >&2
    exit 2
    ;;
esac
RECOVERY_FREQUENCY=$((PREFIX_GLOBAL_STEP + 1))
TAIL_START=$((PREFIX_GLOBAL_STEP + 1))
TAIL_COUNT=$((EXPECTED_UPDATES - TAIL_START))

if [[ "${STUDYHUB_ALLOW_TRAINING:-}" != "YES" || "${STUDYHUB_ALLOW_SFT_RECOVERY_GATE:-}" != "YES" ]]; then
  echo "Set STUDYHUB_ALLOW_TRAINING=YES and STUDYHUB_ALLOW_SFT_RECOVERY_GATE=YES." >&2
  exit 3
fi
if [[ -n "$(git -C "${PROJECT_ROOT}/.." status --porcelain)" ]]; then
  echo "The SFT recovery Gate requires a clean Git worktree." >&2
  exit 4
fi
if [[ ! -x "${VENV_DIR}/bin/areal" ]]; then
  echo "Missing pinned AReaL environment: ${VENV_DIR}" >&2
  exit 1
fi

export PATH="${VENV_DIR}/bin:${PATH}"
unset PYTHONHOME ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy
export STUDYHUB_AREAL_CHAT_TEMPLATE_METADATA_BRIDGE=1
export STUDYHUB_AREAL_SCHEDULER_BRIDGE=1
export STUDYHUB_AREAL_SCHEDULER_TOTAL_STEPS="${SCHEDULER_TOTAL_STEPS}"
export PYTHONPATH="${RUNTIME_SHIM}:${PROJECT_ROOT}:${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
export CUDA_VISIBLE_DEVICES="${GPUS}"
export WANDB_MODE=disabled HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export PYTORCH_ALLOC_CONF=expandable_segments:True

"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/preflight_open_only_sft_v1.py" \
  --config "${CONFIG}" \
  --program "${PROGRAM}" \
  --authorization "${AUTHORIZATION}" \
  --data-card "${DATA_CARD}" \
  --gpus "${GPUS}" \
  --min-free-mib "${MIN_FREE}" >/dev/null

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
GATE_ID="open-only-sft-v1-1-recovery-gate-${PROFILE}-${TIMESTAMP}"
EXPERIMENT="studyhub-${GATE_ID}"
LOG_ROOT="${PROJECT_ROOT}/artifacts/areal/launcher_logs/${GATE_ID}"
CONTINUOUS_TRIAL="${GATE_ID}-continuous"
RECOVERED_TRIAL="${GATE_ID}-recovered"
CONTINUOUS_ATTEMPT="${CONTINUOUS_TRIAL}-attempt-full"
RECOVERED_SECOND_ATTEMPT="${RECOVERED_TRIAL}-attempt-after-recovery"
CONTINUOUS_ROOT="${PROJECT_ROOT}/artifacts/areal/checkpoints/$(id -un)/${EXPERIMENT}/${CONTINUOUS_TRIAL}"
RECOVERED_ROOT="${PROJECT_ROOT}/artifacts/areal/checkpoints/$(id -un)/${EXPERIMENT}/${RECOVERED_TRIAL}"
SHARED_PREFIX_REPORT="${LOG_ROOT}/shared-prefix-snapshot.json"
mkdir -p "${LOG_ROOT}"

run_attempt() {
  local trial="$1"
  local attempt="$2"
  local total_steps="$3"
  local recover_step="$4"
  local snapshot_mode="$5"
  local log_file="${LOG_ROOT}/${attempt}.log"
  local gpu_csv="${LOG_ROOT}/${attempt}.gpu.csv"
  local run_metadata="${LOG_ROOT}/${attempt}.run.json"
  local checkpoint_root="${PROJECT_ROOT}/artifacts/areal/checkpoints/$(id -un)/${EXPERIMENT}/${trial}"
  local train_overrides=(
    "experiment_name=${EXPERIMENT}"
    "trial_name=${trial}"
    "seed=${SEED}"
    "total_train_steps=${total_steps}"
    "saver.freq_steps=${EXPECTED_UPDATES}"
    "saver.freq_secs=null"
    "recover.mode=auto"
    "recover.freq_steps=${RECOVERY_FREQUENCY}"
    "recover.freq_secs=null"
    "evaluator.freq_steps=null"
    "evaluator.freq_secs=null"
  )
  local metadata_args=()

  if [[ ! "${recover_step}" =~ ^[0-9]+$ ]]; then
    echo "Recovery Gate start step is not a non-negative integer: ${recover_step}" >&2
    return 64
  fi
  if [[ "${recover_step}" -gt 0 ]]; then
    export STUDYHUB_AREAL_RECOVER_SCHEDULER_STEP="${recover_step}"
  else
    unset STUDYHUB_AREAL_RECOVER_SCHEDULER_STEP || true
  fi
  for override in "${train_overrides[@]}"; do
    metadata_args+=(--override "${override}")
  done
  metadata_args+=(
    --override "studyhub_attempt_start_step=${recover_step}"
    --override "studyhub_scheduler_total_steps=${SCHEDULER_TOTAL_STEPS}"
    --override "studyhub_gate_id=${GATE_ID}"
    --override "studyhub_gate_scope=${GATE_SCOPE}"
  )

  export STUDYHUB_AREAL_RECOVERY_STATE_BRIDGE=1
  export STUDYHUB_RECOVERY_AUDIT_ROOT="${LOG_ROOT}/${attempt}.recovery-audit"
  export STUDYHUB_RECOVERY_AUDIT_START_STEP="${recover_step}"
  if [[ "${snapshot_mode}" == "snapshot" ]]; then
    export STUDYHUB_RECOVERY_SNAPSHOT_STEP="${PREFIX_GLOBAL_STEP}"
    export STUDYHUB_RECOVERY_SNAPSHOT_TARGET="${RECOVERED_ROOT}"
    export STUDYHUB_RECOVERY_SNAPSHOT_REPORT="${SHARED_PREFIX_REPORT}"
  else
    unset STUDYHUB_RECOVERY_SNAPSHOT_STEP || true
    unset STUDYHUB_RECOVERY_SNAPSHOT_TARGET || true
    unset STUDYHUB_RECOVERY_SNAPSHOT_REPORT || true
  fi

  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" start \
    --output "${run_metadata}" \
    --project "${PROJECT_ROOT}" \
    --run-mode "open-only-sft-v1-1-recovery-gate" \
    --config "${CONFIG}" \
    --dataset-manifest "${DATA_MANIFEST}" \
    --data-card "${DATA_CARD}" \
    --benchmark-manifest "${BENCHMARK_MANIFEST}" \
    --model "${MODEL}" \
    --model-hash-cache "${MODEL_HASH_CACHE}" \
    --areal-lock "${PROJECT_ROOT}/training/areal/upstream.lock.json" \
    --hermes-lock "${PROJECT_ROOT}/integrations/hermes/upstream.lock.json" \
    --gpu "${GPUS}" \
    --max-used-mib "${MAX_USED}" \
    --min-free-mib "${MIN_FREE}" \
    --log-file "${log_file}" \
    --gpu-csv "${gpu_csv}" \
    "${metadata_args[@]}"

  set +e
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/guarded_gpu_launch.py" \
    --gpus "${GPUS}" \
    --min-free-mib "${MIN_FREE}" \
    --max-used-mib "${MAX_USED}" \
    --max-wall-seconds 3600 \
    --interrupt-grace-seconds 180 \
    --log "${log_file}" \
    --gpu-csv "${gpu_csv}" \
    -- "${VENV_DIR}/bin/areal" train run \
    --config "${CONFIG}" \
    --driver training.sft.open_bootstrap_driver:main \
    "${train_overrides[@]}"
  local status=$?
  set -e

  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" finish \
    --output "${run_metadata}" \
    --gpu-csv "${gpu_csv}" \
    --status "${status}"
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/build_experiment_evidence.py" \
    --run-metadata "${run_metadata}" \
    --checkpoint-root "${checkpoint_root}" \
    --evidence-tier DIAGNOSTIC >/dev/null
  if [[ "${status}" -ne 0 ]]; then
    tail -80 "${log_file}" >&2
    return "${status}"
  fi
}

run_attempt \
  "${CONTINUOUS_TRIAL}" \
  "${CONTINUOUS_ATTEMPT}" \
  "${EXPECTED_UPDATES}" \
  0 \
  snapshot
if [[ ! -f "${SHARED_PREFIX_REPORT}" ]]; then
  echo "The synchronous non-destructive snapshot did not produce a report." >&2
  exit 65
fi

RECOVER_STEP_INFO="${PROJECT_ROOT}/artifacts/areal/checkpoints/$(id -un)/${EXPERIMENT}/${RECOVERED_TRIAL}/recover_info/step_info.json"
RECOVER_START="$("${VENV_DIR}/bin/python" -S - "${RECOVER_STEP_INFO}" "${PREFIX_GLOBAL_STEP}" <<'PY'
import json, pathlib, sys
path=pathlib.Path(sys.argv[1])
value=json.loads(path.read_text())
expected=int(sys.argv[2])
if int(value["global_step"]) != expected:
    raise SystemExit(f"expected a recovery checkpoint at global step {expected}, got {value}")
print(int(value["global_step"])+1)
PY
)"
if [[ ! "${RECOVER_START}" =~ ^[0-9]+$ ]]; then
  echo "Recovery Gate extracted an invalid start step: ${RECOVER_START}" >&2
  exit 64
fi
run_attempt \
  "${RECOVERED_TRIAL}" \
  "${RECOVERED_SECOND_ATTEMPT}" \
  "${EXPECTED_UPDATES}" \
  "${RECOVER_START}" \
  no-snapshot

CONTINUOUS_METRICS="${PROJECT_ROOT}/artifacts/experiments/${CONTINUOUS_ATTEMPT}/metrics/trainer.json"
RECOVERED_SECOND_METRICS="${PROJECT_ROOT}/artifacts/experiments/${RECOVERED_SECOND_ATTEMPT}/metrics/trainer.json"
FINAL_GLOBAL_STEP=$((EXPECTED_UPDATES - 1))
CONTINUOUS_ADAPTER="${CONTINUOUS_ROOT}/default/epoch0epochstep${FINAL_GLOBAL_STEP}globalstep${FINAL_GLOBAL_STEP}/adapter_model.safetensors"
RECOVERED_ADAPTER="${RECOVERED_ROOT}/default/epoch0epochstep${FINAL_GLOBAL_STEP}globalstep${FINAL_GLOBAL_STEP}/adapter_model.safetensors"
INITIAL_ADAPTER="${CONTINUOUS_ROOT}/actor/initial_lora/adapter_model.safetensors"
GATE_REPORT="${PROJECT_ROOT}/docs/training/evidence/${GATE_ID}.json"
CONTINUOUS_AUDIT_ROOT="${LOG_ROOT}/${CONTINUOUS_ATTEMPT}.recovery-audit"
RECOVERED_AUDIT_ROOT="${LOG_ROOT}/${RECOVERED_SECOND_ATTEMPT}.recovery-audit"
CONTINUOUS_RUN_METADATA="${LOG_ROOT}/${CONTINUOUS_ATTEMPT}.run.json"
RECOVERED_RUN_METADATA="${LOG_ROOT}/${RECOVERED_SECOND_ATTEMPT}.run.json"

"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/verify_sft_recovery_gate.py" \
  --continuous-segment "${CONTINUOUS_METRICS},0,${EXPECTED_UPDATES}" \
  --recovered-segment "${CONTINUOUS_METRICS},0,${RECOVER_START}" \
  --recovered-segment "${RECOVERED_SECOND_METRICS},${RECOVER_START},${TAIL_COUNT}" \
  --shared-prefix-report "${SHARED_PREFIX_REPORT}" \
  --equivalence-contract "${EQUIVALENCE_CONTRACT}" \
  --continuous-tail-metrics "${CONTINUOUS_METRICS}" \
  --recovered-tail-metrics "${RECOVERED_SECOND_METRICS}" \
  --continuous-audit-root "${CONTINUOUS_AUDIT_ROOT}" \
  --recovered-audit-root "${RECOVERED_AUDIT_ROOT}" \
  --continuous-run-metadata "${CONTINUOUS_RUN_METADATA}" \
  --recovered-run-metadata "${RECOVERED_RUN_METADATA}" \
  --boundary-scope "${GATE_SCOPE}" \
  --expected-prefix-global-step "${PREFIX_GLOBAL_STEP}" \
  --tail-start "${TAIL_START}" \
  --tail-count "${TAIL_COUNT}" \
  --continuous-adapter "${CONTINUOUS_ADAPTER}" \
  --recovered-adapter "${RECOVERED_ADAPTER}" \
  --initial-adapter "${INITIAL_ADAPTER}" \
  --base-lr "${BASE_LR}" \
  --scheduler-total-steps "${SCHEDULER_TOTAL_STEPS}" \
  --warmup-fraction "${WARMUP_FRACTION}" \
  --expected-updates "${EXPECTED_UPDATES}" \
  --output "${GATE_REPORT}"

printf 'SFT recovery Gate passed: %s\n' "${GATE_REPORT}"
