#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-train"
CONFIG="${STUDYHUB_TRAIN_CONFIG:-${PROJECT_ROOT}/configs/train/open-sft-2b-pilot-v2.yaml}"
DATASET_MANIFEST="${STUDYHUB_DATASET_MANIFEST:-${PROJECT_ROOT}/datasets/processed/open_sft_bootstrap_v2/manifest.json}"
PHYSICAL_GPU="${STUDYHUB_TRAIN_GPU:-0}"
MAX_USED_MIB="${STUDYHUB_MAX_GPU_USED_MIB:-28672}"
MIN_FREE_MIB="${STUDYHUB_MIN_GPU_FREE_MIB:-60000}"
LOG_DIR="${PROJECT_ROOT}/artifacts/areal/launcher_logs"
RUN_MODE="${1:-pilot}"

case "${RUN_MODE}" in
  gate) EXTRA_ARGS=(total_train_steps=1 saver.freq_steps=1) ;;
  pilot) EXTRA_ARGS=() ;;
  *) echo "Usage: $0 [gate|pilot]" >&2; exit 2 ;;
esac

if [[ ! -x "${VENV_DIR}/bin/areal" ]]; then
  echo "Missing AReaL environment. Run scripts/train/setup_areal_env.sh first." >&2
  exit 1
fi

mapfile -t existing_pids < <(
  nvidia-smi -i "${PHYSICAL_GPU}" --query-compute-apps=pid --format=csv,noheader,nounits 2>/dev/null \
    | tr -d ' ' | sed '/^$/d'
)
if (( ${#existing_pids[@]} > 0 )); then
  echo "GPU ${PHYSICAL_GPU} already has compute processes: ${existing_pids[*]}" >&2
  exit 1
fi

free_mib="$(nvidia-smi -i "${PHYSICAL_GPU}" --query-gpu=memory.free --format=csv,noheader,nounits | tr -d ' ')"
if (( free_mib < MIN_FREE_MIB )); then
  echo "GPU ${PHYSICAL_GPU} has only ${free_mib} MiB free; require ${MIN_FREE_MIB} MiB." >&2
  exit 1
fi

mkdir -p "${LOG_DIR}"
timestamp="$(date +%Y%m%d_%H%M%S)"
if [[ "${RUN_MODE}" == "gate" ]]; then
  EXTRA_ARGS+=(trial_name="gate-grouped-sdpa-${timestamp}")
else
  EXTRA_ARGS+=(trial_name="pilot-grouped-r16-lr2e5-seed1-${timestamp}")
fi
log_file="${LOG_DIR}/${RUN_MODE}_${timestamp}.log"
gpu_csv="${LOG_DIR}/${RUN_MODE}_${timestamp}.gpu.csv"
run_metadata="${LOG_DIR}/${RUN_MODE}_${timestamp}.run.json"
cd "${PROJECT_ROOT}"

TRAIN_STATUS=""
finalize_metadata() {
  local shell_status=$?
  trap - EXIT
  if [[ -f "${run_metadata}" ]]; then
    "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" finish \
      --output "${run_metadata}" \
      --gpu-csv "${gpu_csv}" \
      --status "${TRAIN_STATUS:-${shell_status}}" || true
  fi
}
trap finalize_metadata EXIT

printf 'timestamp,index,memory_used_mib,memory_free_mib,utilization_gpu_pct,power_w\n' >"${gpu_csv}"
metadata_args=()
for override in "${EXTRA_ARGS[@]}"; do
  metadata_args+=(--override "${override}")
done
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/capture_run_metadata.py" start \
  --output "${run_metadata}" \
  --project "${PROJECT_ROOT}" \
  --run-mode "${RUN_MODE}" \
  --config "${CONFIG}" \
  --dataset-manifest "${DATASET_MANIFEST}" \
  --model "${PROJECT_ROOT}/../models/P0/Qwen3.5-2B" \
  --areal-lock "${PROJECT_ROOT}/training/areal/upstream.lock.json" \
  --gpu "${PHYSICAL_GPU}" \
  --max-used-mib "${MAX_USED_MIB}" \
  --min-free-mib "${MIN_FREE_MIB}" \
  --log-file "${log_file}" \
  --gpu-csv "${gpu_csv}" \
  "${metadata_args[@]}"

setsid env \
  -u ALL_PROXY -u all_proxy \
  -u HTTP_PROXY -u http_proxy \
  -u HTTPS_PROXY -u https_proxy \
  CUDA_VISIBLE_DEVICES="${PHYSICAL_GPU}" \
  WANDB_MODE=disabled \
  HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  TOKENIZERS_PARALLELISM=false \
  PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" \
  PYTORCH_ALLOC_CONF=expandable_segments:True \
  "${VENV_DIR}/bin/areal" train run \
    --config "${CONFIG}" \
    --driver training.sft.open_bootstrap_driver:main \
    "${EXTRA_ARGS[@]}" >"${log_file}" 2>&1 &
train_pid=$!

terminate_own_training() {
  kill -TERM -- "-${train_pid}" 2>/dev/null || true
  sleep 5
  kill -KILL -- "-${train_pid}" 2>/dev/null || true
}
trap terminate_own_training INT TERM

echo "Training PID ${train_pid}; log ${log_file}"
while kill -0 "${train_pid}" 2>/dev/null; do
  sample="$(nvidia-smi -i "${PHYSICAL_GPU}" --query-gpu=index,memory.used,memory.free,utilization.gpu,power.draw --format=csv,noheader,nounits | tr -d ' ')"
  printf '%s,%s\n' "$(date --iso-8601=seconds)" "${sample}" >>"${gpu_csv}"
  used_mib="$(cut -d, -f2 <<<"${sample}")"
  if (( used_mib > MAX_USED_MIB )); then
    echo "Memory guard tripped at ${used_mib} MiB; stopping only StudyHub's process group." | tee -a "${log_file}" >&2
    terminate_own_training
    wait "${train_pid}" || true
    exit 70
  fi
  while read -r gpu_pid; do
    [[ -z "${gpu_pid}" ]] && continue
    owner="$(ps -o user= -p "${gpu_pid}" 2>/dev/null | xargs || true)"
    if [[ -n "${owner}" && "${owner}" != "$(id -un)" ]]; then
      echo "Foreign GPU process ${gpu_pid} (${owner}) appeared; yielding GPU." | tee -a "${log_file}" >&2
      terminate_own_training
      wait "${train_pid}" || true
      exit 71
    fi
  done < <(
    nvidia-smi -i "${PHYSICAL_GPU}" --query-compute-apps=pid --format=csv,noheader,nounits 2>/dev/null \
      | tr -d ' ' | sed '/^$/d'
  )
  sleep 5
done

set +e
wait "${train_pid}"
status=$?
set -e
TRAIN_STATUS="${status}"
kill -TERM -- "-${train_pid}" 2>/dev/null || true
sleep 2
kill -KILL -- "-${train_pid}" 2>/dev/null || true
tail -80 "${log_file}"
exit "${status}"
