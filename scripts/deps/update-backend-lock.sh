#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${STUDYHUB_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "missing Python interpreter: $PYTHON_BIN" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -m piptools compile --version >/dev/null 2>&1; then
  echo "missing pip-tools; install it with: $PYTHON_BIN -m pip install pip-tools==7.5.2" >&2
  exit 1
fi

cd "$ROOT_DIR"
CUSTOM_COMPILE_COMMAND="bash scripts/deps/update-backend-lock.sh" \
PIP_INDEX_URL="${STUDYHUB_PYPI_INDEX_URL:-https://pypi.org/simple}" \
  "$PYTHON_BIN" -m piptools compile \
  --extra=dev \
  --generate-hashes \
  --strip-extras \
  --resolver=backtracking \
  --no-emit-index-url \
  --no-emit-trusted-host \
  --output-file=backend/requirements.lock \
  backend/pyproject.toml
