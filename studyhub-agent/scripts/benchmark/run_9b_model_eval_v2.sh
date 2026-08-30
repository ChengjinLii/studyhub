#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${PROJECT_ROOT}/.venv-train"
MODE="${1:-gate}"
SEED="${2:-20260827}"
GPUS="${STUDYHUB_EVAL_GPUS:-0,1}"
MODEL="${STUDYHUB_EVAL_MODEL:-${PROJECT_ROOT}/../models/P1/Qwen3.5-9B}"
MODEL_ROLE="${STUDYHUB_EVAL_MODEL_ROLE:-base}"
MODEL_RUN_PREFIX="${STUDYHUB_EVAL_MODEL_RUN_PREFIX:-qwen35-9b}"

case "${MODE}" in
  gate|regression|development|variance) ;;
  *) echo "Usage: $0 <gate|regression|development|variance> [seed]" >&2; exit 2 ;;
esac
if [[ ! "${MODEL_ROLE}" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "STUDYHUB_EVAL_MODEL_ROLE must contain only lowercase letters, digits and hyphens." >&2
  exit 2
fi
if [[ ! "${MODEL_RUN_PREFIX}" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "STUDYHUB_EVAL_MODEL_RUN_PREFIX must contain only lowercase letters, digits and hyphens." >&2
  exit 2
fi
if [[ "${STUDYHUB_ALLOW_EVALUATION:-}" != "YES" ]]; then
  echo "Refusing to launch. Set STUDYHUB_ALLOW_EVALUATION=YES." >&2
  exit 3
fi
if [[ ! -x "${VENV}/bin/python" ]]; then
  echo "Missing fixed training environment: ${VENV}" >&2
  exit 1
fi

IFS=',' read -r -a GPU_ARRAY <<<"${GPUS}"
if [[ "${#GPU_ARRAY[@]}" -ne 2 ]]; then
  echo "STUDYHUB_EVAL_GPUS must contain exactly two GPU IDs." >&2
  exit 2
fi

export PATH="${VENV}/bin:${PATH}"
unset PYTHONHOME
unset ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export STUDYHUB_DISABLE_DEEP_GEMM_WITHOUT_NVCC=1
export STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC=1
export PYTHONPATH="${PROJECT_ROOT}/training/runtime_shims:${PROJECT_ROOT}:${PROJECT_ROOT}/src"

MANIFEST="${PROJECT_ROOT}/benchmarks/studyhub-agent-v2/manifest.json"
"${VENV}/bin/python" - "${MODEL}" "${MANIFEST}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

from scripts.benchmark.run_9b_base_eval import resolve_model_artifact

model = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("status") != "FROZEN_FOR_BASELINE":
    raise SystemExit("Benchmark v2 is not frozen")
identity, model_manifest = resolve_model_artifact(model)
print(
    f"benchmark_manifest_sha256={hashlib.sha256(manifest_path.read_bytes()).hexdigest()} "
    f"builder={manifest['builder_commit']} model={identity} "
    f"model_manifest={model_manifest['schema_version']}"
)
PY

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
TRIAL="${MODEL_RUN_PREFIX}-${MODEL_ROLE}-v2-${MODE}-seed-${SEED}-${TIMESTAMP}"
LAUNCH_ROOT="${PROJECT_ROOT}/artifacts/benchmark-v2/launcher"
LOG_FILE="${LAUNCH_ROOT}/${TRIAL}.log"
GPU_CSV="${LAUNCH_ROOT}/${TRIAL}.gpu.csv"
mkdir -p "${LAUNCH_ROOT}"

set +e
"${VENV}/bin/python" "${PROJECT_ROOT}/scripts/train/guarded_gpu_launch.py" \
  --gpus "${GPUS}" \
  --min-free-mib "${STUDYHUB_MIN_GPU_FREE_MIB:-76000}" \
  --max-used-mib "${STUDYHUB_MAX_GPU_USED_MIB:-76000}" \
  --log "${LOG_FILE}" \
  --gpu-csv "${GPU_CSV}" \
  -- "${VENV}/bin/python" "${PROJECT_ROOT}/scripts/benchmark/run_9b_base_eval.py" \
    "${MODE}" \
    --benchmark-version v2 \
    --model "${MODEL}" \
    --trial "${TRIAL}" \
    --seed "${SEED}" \
    --workers 2 \
    --gpus "${GPU_ARRAY[0]}" "${GPU_ARRAY[1]}"
RUN_STATUS=$?
set -e

RUN_MANIFEST="${PROJECT_ROOT}/artifacts/benchmark-v2/runs/${TRIAL}/run-manifest.json"
if [[ -f "${RUN_MANIFEST}" && -s "${GPU_CSV}" && -s "${LOG_FILE}" ]]; then
  "${VENV}/bin/python" "${PROJECT_ROOT}/scripts/benchmark/attach_run_evidence.py" \
    --manifest "${RUN_MANIFEST}" \
    --gpu-telemetry "${GPU_CSV}" \
    --launcher-log "${LOG_FILE}"
fi

printf 'Run: %s\n' "${TRIAL}"
printf 'Model: %s\n' "${MODEL}"
printf 'Summary: %s\n' "${PROJECT_ROOT}/artifacts/benchmark-v2/runs/${TRIAL}/summary.json"
printf 'GPU telemetry: %s\n' "${GPU_CSV}"
exit "${RUN_STATUS}"
