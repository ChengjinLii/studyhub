#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BASE_SCRIPT="${SCRIPT_DIR}/download_models.sh"
MODE=${1:-official}

usage() {
  cat <<'EOF'
Usage:
  bash scripts/ai/download_models_p1.sh [official|full]

Modes:
  official  Download the verified official P1 model set.
  full      Download the official set first, then optional quantized comparator repos if env vars are set.

Optional env vars for quantized/community comparator repos:
  P1_GEMMA_4_31B_FP8_REPO
  P1_GEMMA_4_31B_Q4_REPO
  P1_GEMMA_4_26B_A4B_FP8_REPO
  P1_GEMMA_4_26B_A4B_Q4_REPO
  P1_QWEN3_8B_Q4_REPO

Retry behavior is inherited from download_models.sh:
  HF_MAX_WORKERS
  HF_RETRY_COUNT
  HF_RETRY_DELAY_SECONDS

Proxy behavior is also inherited from download_models.sh:
  HF_PROXY_URL     Defaults to http://127.0.0.1:7892
EOF
}

if [[ "${MODE}" != "official" && "${MODE}" != "full" ]]; then
  usage >&2
  exit 1
fi

declare -a ordered_targets=(
  "Qwen3.6-27B"
  "Qwen3-Embedding-4B"
  "Qwen3-Embedding-8B"
  "Qwen3-Reranker-4B"
  "Qwen3-Reranker-8B"
  "Qwen3-8B"
  "gemma-4-31B-it"
  "gemma-4-26B-A4B-it"
)

for target in "${ordered_targets[@]}"; do
  echo "==== P1 official: ${target} ===="
  bash "${BASE_SCRIPT}" "${target}"
done

if [[ "${MODE}" == "official" ]]; then
  echo "P1 official downloads completed."
  exit 0
fi

declare -a optional_repo_vars=(
  "P1_GEMMA_4_31B_FP8_REPO"
  "P1_GEMMA_4_31B_Q4_REPO"
  "P1_GEMMA_4_26B_A4B_FP8_REPO"
  "P1_GEMMA_4_26B_A4B_Q4_REPO"
  "P1_QWEN3_8B_Q4_REPO"
)

for var_name in "${optional_repo_vars[@]}"; do
  repo_id="${!var_name:-}"
  if [[ -z "${repo_id}" ]]; then
    echo "==== Skip optional comparator: ${var_name} is not set ===="
    continue
  fi
  echo "==== P1 optional: ${var_name} -> ${repo_id} ===="
  bash "${BASE_SCRIPT}" "${repo_id}"
done

echo "P1 full downloads completed."
