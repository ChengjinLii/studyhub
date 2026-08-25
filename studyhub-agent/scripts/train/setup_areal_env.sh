#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_DIR="${PROJECT_ROOT}/.cache/areal-src"
VENV_DIR="${PROJECT_ROOT}/.venv-train"
AREAL_REPOSITORY="https://github.com/areal-project/AReaL.git"
AREAL_COMMIT="cbff54d645d2cd8ee1f1c358a82f3f473588433d"
PROXY_URL="${STUDYHUB_DOWNLOAD_PROXY:-http://127.0.0.1:7892}"
PROFILE="${1:-sft}"

case "${PROFILE}" in
  sft) SYNC_EXTRAS=() ;;
  rl) SYNC_EXTRAS=(--extra sglang) ;;
  *) echo "Usage: $0 [sft|rl]" >&2; exit 2 ;;
esac

if [[ "${PROXY_URL}" != "http://127.0.0.1:7892" ]]; then
  echo "Only http://127.0.0.1:7892 is allowed for dependency downloads." >&2
  exit 2
fi

export HTTP_PROXY="${PROXY_URL}"
export HTTPS_PROXY="${PROXY_URL}"
export ALL_PROXY="${PROXY_URL}"
export http_proxy="${PROXY_URL}"
export https_proxy="${PROXY_URL}"
export all_proxy="${PROXY_URL}"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="${NO_PROXY}"

if [[ ! -d "${SOURCE_DIR}/.git" ]]; then
  if [[ -e "${SOURCE_DIR}" ]]; then
    echo "${SOURCE_DIR} exists but is not an AReaL Git checkout; refusing to replace it." >&2
    exit 1
  fi
  git clone "${AREAL_REPOSITORY}" "${SOURCE_DIR}"
else
  CURRENT_REMOTE="$(git -C "${SOURCE_DIR}" remote get-url origin)"
  if [[ "${CURRENT_REMOTE%.git}" != "${AREAL_REPOSITORY%.git}" ]]; then
    echo "AReaL checkout has unexpected origin: ${CURRENT_REMOTE}" >&2
    exit 1
  fi
fi

git -C "${SOURCE_DIR}" fetch origin "${AREAL_COMMIT}"
git -C "${SOURCE_DIR}" checkout --detach "${AREAL_COMMIT}"

UV_PROJECT_ENVIRONMENT="${VENV_DIR}" \
  uv sync --project "${SOURCE_DIR}" --frozen --no-dev "${SYNC_EXTRAS[@]}"

"${VENV_DIR}/bin/python" - "${PROFILE}" <<'PY'
import importlib.metadata
import importlib.util
import sys

import areal
import peft
import torch
import transformers

profile = sys.argv[1]
result = {
    "profile": profile,
    "areal": areal.__version__,
    "torch": torch.__version__,
    "transformers": transformers.__version__,
    "peft": peft.__version__,
    "cuda_available": torch.cuda.is_available(),
    "sglang": importlib.metadata.version("sglang")
    if importlib.util.find_spec("sglang")
    else None,
}
if profile == "rl" and result["sglang"] is None:
    raise SystemExit("RL profile requested but SGLang is not installed")
print(result)
PY
