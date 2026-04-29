#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
MODEL_ROOT=${MODEL_ROOT:-"${REPO_ROOT}/models"}
TIER=${1:-p0-core}
export PATH="${HOME}/.local/bin:${PATH}"
export HF_HUB_DISABLE_XET=1
HF_MAX_WORKERS=${HF_MAX_WORKERS:-1}
HF_RETRY_COUNT=${HF_RETRY_COUNT:-5}
HF_RETRY_DELAY_SECONDS=${HF_RETRY_DELAY_SECONDS:-10}
HF_PROXY_URL=${HF_PROXY_URL:-http://127.0.0.1:7892}

if [[ -n "${HF_PROXY_URL}" ]]; then
  export HTTP_PROXY="${HTTP_PROXY:-${HF_PROXY_URL}}"
  export HTTPS_PROXY="${HTTPS_PROXY:-${HF_PROXY_URL}}"
  export ALL_PROXY="${ALL_PROXY:-${HF_PROXY_URL}}"
  export http_proxy="${http_proxy:-${HTTP_PROXY}}"
  export https_proxy="${https_proxy:-${HTTPS_PROXY}}"
  export all_proxy="${all_proxy:-${ALL_PROXY}}"
fi
export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost}"
export no_proxy="${no_proxy:-${NO_PROXY}}"

mkdir -p "${MODEL_ROOT}"

ensure_hf_cli() {
  if command -v hf >/dev/null 2>&1; then
    return
  fi
  python -m pip install --user "huggingface_hub[cli]>=0.31,<1.0"
}

hf_dns_ready() {
  if [[ -n "${HTTPS_PROXY:-}" || -n "${HTTP_PROXY:-}" || -n "${ALL_PROXY:-}" || -n "${https_proxy:-}" || -n "${http_proxy:-}" || -n "${all_proxy:-}" ]]; then
    return 0
  fi
  getent ahosts huggingface.co >/dev/null 2>&1
}

cleanup_stale_download_artifacts() {
  local target_dir="$1"
  if [[ ! -d "${target_dir}" ]]; then
    return
  fi
  find "${target_dir}" -path '*/.cache/huggingface/download/*.lock' -type f -delete 2>/dev/null || true
  find "${target_dir}" -path '*/.cache/huggingface/download/*.incomplete' -type f -size 0c -delete 2>/dev/null || true
}

validate_repo_download() {
  local repo_id="$1"
  local target_dir="$2"
  local count

  case "${repo_id}" in
    "Qwen/Qwen3-1.7B")
      count=$(find "${target_dir}" -maxdepth 1 -type f -name 'model-*.safetensors' | wc -l | tr -d ' ')
      [[ "${count}" == "2" && -f "${target_dir}/model.safetensors.index.json" ]]
      ;;
    "Qwen/Qwen3-4B")
      count=$(find "${target_dir}" -maxdepth 1 -type f -name 'model-*.safetensors' | wc -l | tr -d ' ')
      [[ "${count}" == "3" && -f "${target_dir}/model.safetensors.index.json" ]]
      ;;
    "Qwen/Qwen3.6-27B")
      count=$(find "${target_dir}" -maxdepth 1 -type f -name 'model-*.safetensors' | wc -l | tr -d ' ')
      [[ "${count}" == "15" && -f "${target_dir}/model.safetensors.index.json" ]]
      ;;
    "Qwen/Qwen3-8B")
      count=$(find "${target_dir}" -maxdepth 1 -type f -name 'model-*.safetensors' | wc -l | tr -d ' ')
      [[ "${count}" == "5" && -f "${target_dir}/model.safetensors.index.json" ]]
      ;;
    "Qwen/Qwen3-Embedding-0.6B"|"Qwen/Qwen3-Reranker-0.6B"|"BAAI/bge-reranker-v2-m3")
      [[ -f "${target_dir}/model.safetensors" ]]
      ;;
    "Qwen/Qwen3-Embedding-4B")
      count=$(find "${target_dir}" -maxdepth 1 -type f -name 'model-*.safetensors' | wc -l | tr -d ' ')
      [[ "${count}" == "2" && -f "${target_dir}/model.safetensors.index.json" ]]
      ;;
    "Qwen/Qwen3-Embedding-8B")
      count=$(find "${target_dir}" -maxdepth 1 -type f -name 'model-*.safetensors' | wc -l | tr -d ' ')
      [[ "${count}" == "4" && -f "${target_dir}/model.safetensors.index.json" ]]
      ;;
    "Qwen/Qwen3-Reranker-4B")
      count=$(find "${target_dir}" -maxdepth 1 -type f -name 'model-*.safetensors' | wc -l | tr -d ' ')
      [[ "${count}" == "2" && -f "${target_dir}/model.safetensors.index.json" ]]
      ;;
    "Qwen/Qwen3-Reranker-8B")
      count=$(find "${target_dir}" -maxdepth 1 -type f -name 'model-*.safetensors' | wc -l | tr -d ' ')
      [[ "${count}" == "5" && -f "${target_dir}/model.safetensors.index.json" ]]
      ;;
    "BAAI/bge-m3")
      [[ -f "${target_dir}/pytorch_model.bin" ]]
      ;;
    "google/gemma-4-31B-it"|"google/gemma-4-26B-A4B-it")
      count=$(find "${target_dir}" -maxdepth 1 -type f -name 'model-*.safetensors' | wc -l | tr -d ' ')
      [[ "${count}" == "2" && -f "${target_dir}/model.safetensors.index.json" ]]
      ;;
    "Qwen/Qwen3.6-27B-FP8")
      count=$(find "${target_dir}" -maxdepth 1 -type f -name 'layers-*.safetensors' | wc -l | tr -d ' ')
      [[ "${count}" == "64" && -f "${target_dir}/layers-0.safetensors" && -f "${target_dir}/layers-63.safetensors" ]]
      ;;
    *)
      find "${target_dir}" -maxdepth 1 -type f \( -name '*.safetensors' -o -name '*.bin' \) | grep -q .
      ;;
  esac
}

download_repo() {
  local repo_id="$1"
  local target_dir="$2"
  local attempt=1

  cleanup_stale_download_artifacts "${target_dir}"
  if validate_repo_download "${repo_id}" "${target_dir}"; then
    echo "==> Skipping ${repo_id}; validated files already exist at ${target_dir}"
    return
  fi

  echo "==> Downloading ${repo_id} -> ${target_dir}"
  while (( attempt <= HF_RETRY_COUNT )); do
    if ! hf_dns_ready; then
      echo "DNS lookup failed for huggingface.co; sleeping ${HF_RETRY_DELAY_SECONDS}s before retry." >&2
    elif hf download \
      "${repo_id}" \
      --repo-type model \
      --local-dir "${target_dir}" \
      --max-workers "${HF_MAX_WORKERS}"; then
      if validate_repo_download "${repo_id}" "${target_dir}"; then
        echo "Validated download for ${repo_id}"
        return
      fi
      echo "Validation failed for ${repo_id}; required weight files are missing." >&2
    fi
    if (( attempt == HF_RETRY_COUNT )); then
      echo "Download failed after ${HF_RETRY_COUNT} attempts: ${repo_id}" >&2
      return 1
    fi
    cleanup_stale_download_artifacts "${target_dir}"
    echo "Retry ${attempt}/${HF_RETRY_COUNT} failed for ${repo_id}, sleeping ${HF_RETRY_DELAY_SECONDS}s..." >&2
    sleep "${HF_RETRY_DELAY_SECONDS}"
    attempt=$((attempt + 1))
  done
}

ensure_hf_cli

declare -a repos=()
declare -A repo_alias=(
  ["Qwen3.6-27B"]="Qwen/Qwen3.6-27B"
  ["Qwen3-1.7B"]="Qwen/Qwen3-1.7B"
  ["Qwen3-Embedding-0.6B"]="Qwen/Qwen3-Embedding-0.6B"
  ["Qwen3-Embedding-4B"]="Qwen/Qwen3-Embedding-4B"
  ["Qwen3-Embedding-8B"]="Qwen/Qwen3-Embedding-8B"
  ["Qwen3-Reranker-0.6B"]="Qwen/Qwen3-Reranker-0.6B"
  ["Qwen3-Reranker-4B"]="Qwen/Qwen3-Reranker-4B"
  ["Qwen3-Reranker-8B"]="Qwen/Qwen3-Reranker-8B"
  ["Qwen3-4B"]="Qwen/Qwen3-4B"
  ["Qwen3-8B"]="Qwen/Qwen3-8B"
  ["Qwen3.6-27B-FP8"]="Qwen/Qwen3.6-27B-FP8"
  ["bge-m3"]="BAAI/bge-m3"
  ["bge-reranker-v2-m3"]="BAAI/bge-reranker-v2-m3"
  ["gemma-4-31B-it"]="google/gemma-4-31B-it"
  ["gemma-4-26B-A4B-it"]="google/gemma-4-26B-A4B-it"
)
case "${TIER}" in
  p0-core)
    repos=(
      "Qwen/Qwen3-1.7B"
      "Qwen/Qwen3-Embedding-0.6B"
      "Qwen/Qwen3-Reranker-0.6B"
      "Qwen/Qwen3.6-27B-FP8"
    )
    ;;
  p0)
    repos=(
      "Qwen/Qwen3-1.7B"
      "Qwen/Qwen3-Embedding-0.6B"
      "Qwen/Qwen3-Reranker-0.6B"
      "Qwen/Qwen3-4B"
      "BAAI/bge-m3"
      "BAAI/bge-reranker-v2-m3"
      "Qwen/Qwen3.6-27B-FP8"
    )
    ;;
  p1)
    repos=(
      "Qwen/Qwen3.6-27B"
      "Qwen/Qwen3-Embedding-4B"
      "Qwen/Qwen3-Embedding-8B"
      "Qwen/Qwen3-Reranker-4B"
      "Qwen/Qwen3-Reranker-8B"
      "Qwen/Qwen3-8B"
      "google/gemma-4-31B-it"
      "google/gemma-4-26B-A4B-it"
    )
    ;;
  *)
    if [[ -n "${repo_alias[${TIER}]:-}" ]]; then
      repos=("${repo_alias[${TIER}]}")
    elif [[ "${TIER}" == */* ]]; then
      repos=("${TIER}")
    else
      echo "Unknown tier or repo: ${TIER}" >&2
      echo "Usage: $0 [p0-core|p0|p1|<repo_id>|<repo_alias>]" >&2
      exit 1
    fi
    ;;
esac

for repo_id in "${repos[@]}"; do
  repo_name=${repo_id#*/}
  download_repo "${repo_id}" "${MODEL_ROOT}/${repo_name}"
done

echo "Downloads completed under ${MODEL_ROOT}"
