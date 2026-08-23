#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${STUDYHUB_AGENT_VENV:-${AGENT_DIR}/.venv}"
PYTHON_BIN="${STUDYHUB_AGENT_PYTHON:-python3}"

"${SCRIPT_DIR}/setup-hermes.sh"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -e "${AGENT_DIR}[dev]"
"${VENV_DIR}/bin/python" -m pip install -e "${AGENT_DIR}/ai_platform/rag_experiments"

# Hermes pins its build backend. Install that pin before disabling build
# isolation so mirrors do not silently substitute a different version.
"${VENV_DIR}/bin/python" -m pip install setuptools==83.0.0
"${VENV_DIR}/bin/python" -m pip install --no-build-isolation -e "${AGENT_DIR}/.vendor/hermes-agent"

printf 'StudyHub Agent Phase 1 CPU environment is ready: %s\n' "${VENV_DIR}"
