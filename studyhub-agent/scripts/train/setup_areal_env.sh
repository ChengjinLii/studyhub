#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_DIR="${PROJECT_ROOT}/.cache/areal-src"
VENV_DIR="${PROJECT_ROOT}/.venv-train"
AREAL_COMMIT="cbff54d645d2cd8ee1f1c358a82f3f473588433d"
PROXY_URL="${STUDYHUB_DOWNLOAD_PROXY:-http://127.0.0.1:7892}"

if [[ ! -d "${SOURCE_DIR}/.git" ]]; then
  if [[ -e "${SOURCE_DIR}" ]]; then
    echo "${SOURCE_DIR} exists but is not an AReaL Git checkout; refusing to replace it." >&2
    exit 1
  fi
  git clone https://github.com/areal-project/AReaL.git "${SOURCE_DIR}"
fi

git -C "${SOURCE_DIR}" fetch origin "${AREAL_COMMIT}"
git -C "${SOURCE_DIR}" checkout --detach "${AREAL_COMMIT}"

HTTP_PROXY="${PROXY_URL}" HTTPS_PROXY="${PROXY_URL}" \
  UV_PROJECT_ENVIRONMENT="${VENV_DIR}" \
  uv sync --project "${SOURCE_DIR}" --frozen --no-dev

"${VENV_DIR}/bin/python" - <<'PY'
import areal
import peft
import torch
import transformers

print(
    {
        "areal": areal.__version__,
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "peft": peft.__version__,
        "cuda_available": torch.cuda.is_available(),
    }
)
PY
