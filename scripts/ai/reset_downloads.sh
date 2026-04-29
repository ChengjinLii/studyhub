#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)
MODEL_ROOT=${MODEL_ROOT:-"${REPO_ROOT}/models"}
TIER=${1:-p0-core}
MODE=${2:-resume}
export PATH="${HOME}/.local/bin:${PATH}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/ai/reset_downloads.sh [p0-core|p0|p1|<repo_id>|<repo_alias>] [resume|fresh|no-restart]

Modes:
  resume      Remove stale lock files and zero-byte .incomplete files, then restart downloads.
  fresh       Remove stale lock files and all .incomplete files, then restart downloads.
  no-restart  Only clean stale artifacts, do not restart downloads.
EOF
}

if [[ "${MODE}" != "resume" && "${MODE}" != "fresh" && "${MODE}" != "no-restart" ]]; then
  usage >&2
  exit 1
fi

kill_matching_processes() {
  local pattern
  local killed=0

  for pattern in \
    "${REPO_ROOT}/scripts/ai/download_models.sh" \
    "hf download .*${MODEL_ROOT}" \
    "huggingface.*${MODEL_ROOT}"
  do
    while IFS= read -r line; do
      [[ -z "${line}" ]] && continue
      pid=${line%% *}
      if [[ "${pid}" =~ ^[0-9]+$ ]]; then
        kill "${pid}" 2>/dev/null || true
        killed=1
      fi
    done < <(pgrep -af "${pattern}" || true)
  done

  if (( killed )); then
    sleep 1
  fi
}

clean_artifacts() {
  local lock_count=0
  local incomplete_count=0
  local path

  while IFS= read -r path; do
    [[ -z "${path}" ]] && continue
    rm -f "${path}"
    lock_count=$((lock_count + 1))
  done < <(find "${MODEL_ROOT}" -path '*/.cache/huggingface/download/*.lock' -type f 2>/dev/null || true)

  if [[ "${MODE}" == "fresh" ]]; then
    while IFS= read -r path; do
      [[ -z "${path}" ]] && continue
      rm -f "${path}"
      incomplete_count=$((incomplete_count + 1))
    done < <(find "${MODEL_ROOT}" -path '*/.cache/huggingface/download/*.incomplete' -type f 2>/dev/null || true)
  else
    while IFS= read -r path; do
      [[ -z "${path}" ]] && continue
      rm -f "${path}"
      incomplete_count=$((incomplete_count + 1))
    done < <(find "${MODEL_ROOT}" -path '*/.cache/huggingface/download/*.incomplete' -type f -size 0c 2>/dev/null || true)
  fi

  echo "Cleaned ${lock_count} lock files and ${incomplete_count} incomplete files under ${MODEL_ROOT}"
}

mkdir -p "${MODEL_ROOT}"

kill_matching_processes
clean_artifacts

if [[ "${MODE}" == "no-restart" ]]; then
  echo "Cleanup only. Downloads were not restarted."
  exit 0
fi

exec "${REPO_ROOT}/scripts/ai/download_models.sh" "${TIER}"
