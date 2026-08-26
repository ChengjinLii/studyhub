#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-train"
MODE="${1:-verify}"
PROXY_URL="http://127.0.0.1:7892"
export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

case "${MODE}" in
  verify|rebuild) ;;
  *) echo "Usage: $0 [verify|rebuild]" >&2; exit 2 ;;
esac

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Missing ${VENV_DIR}; run scripts/train/setup_areal_env.sh rl first." >&2
  exit 1
fi

export PATH="${VENV_DIR}/bin:${PATH}"
unset PYTHONHOME

if [[ "${MODE}" == "rebuild" ]]; then
  bash "${PROJECT_ROOT}/scripts/models/download_qwen35_controlled.sh" all
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/data/download_open_sft_sources.py" \
    --proxy "${PROXY_URL}"
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/data/build_open_sft_bootstrap.py"
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/data/tokenize_areal_sft.py" \
    --model "${PROJECT_ROOT}/../models/P1/Qwen3.5-4B" \
    --output "${PROJECT_ROOT}/datasets/processed/open_sft_bootstrap_v2_qwen35_4b" \
    --max-length 2048 \
    --overwrite
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/data/tokenize_areal_sft.py" \
    --model "${PROJECT_ROOT}/../models/P1/Qwen3.5-9B" \
    --output "${PROJECT_ROOT}/datasets/processed/open_sft_bootstrap_v2_qwen35_9b" \
    --max-length 2048 \
    --overwrite
  "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/data/build_open_rl_tasks.py" \
    --overwrite
else
  bash "${PROJECT_ROOT}/scripts/models/download_qwen35_controlled.sh" verify
fi

"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/data/verify_open_sft_dataset.py" \
  --dataset "${PROJECT_ROOT}/datasets/processed/open_sft_bootstrap_v2_qwen35_4b" \
  --output "${PROJECT_ROOT}/artifacts/areal/dataset-audit-qwen35-4b.json"
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/data/verify_open_sft_dataset.py" \
  --dataset "${PROJECT_ROOT}/datasets/processed/open_sft_bootstrap_v2_qwen35_9b" \
  --output "${PROJECT_ROOT}/artifacts/areal/dataset-audit-qwen35-9b.json"
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/data/verify_open_rl_dataset.py" \
  --dataset "${PROJECT_ROOT}/datasets/processed/open_agent_rl_v1" \
  --output "${PROJECT_ROOT}/artifacts/areal/open-rl-dataset-audit-v1.json"
"${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/preflight_controlled_experiment.py"

printf 'Preparation complete. No training command was executed.\n'
