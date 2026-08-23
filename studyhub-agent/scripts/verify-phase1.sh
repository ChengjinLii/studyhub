#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${STUDYHUB_AGENT_VENV:-${AGENT_DIR}/.venv}"
PYTHON_BIN="${VENV_DIR}/bin/python"
HERMES_DIR="${STUDYHUB_HERMES_DIR:-${AGENT_DIR}/.vendor/hermes-agent}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  printf 'Agent virtual environment is missing; run bootstrap-phase1.sh first.\n' >&2
  exit 1
fi

EXPECTED_HERMES_COMMIT="$("${PYTHON_BIN}" - "${AGENT_DIR}/integrations/hermes/upstream.lock.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["commit"])
PY
)"
ACTUAL_HERMES_COMMIT="$(git -C "${HERMES_DIR}" rev-parse HEAD)"

if [[ "${ACTUAL_HERMES_COMMIT}" != "${EXPECTED_HERMES_COMMIT}" ]]; then
  printf 'Hermes commit mismatch: expected %s, got %s\n' "${EXPECTED_HERMES_COMMIT}" "${ACTUAL_HERMES_COMMIT}" >&2
  exit 1
fi
if [[ -n "$(git -C "${HERMES_DIR}" status --porcelain)" ]]; then
  printf 'Hermes checkout contains local changes.\n' >&2
  exit 1
fi

"${PYTHON_BIN}" -m ruff check "${AGENT_DIR}/src" "${AGENT_DIR}/training" "${AGENT_DIR}/tests"
"${PYTHON_BIN}" -m pytest -n 0 "${AGENT_DIR}/tests" -q

(
  cd "${AGENT_DIR}/ai_platform/rag_experiments"
  "${PYTHON_BIN}" -m pytest -n 0 -q
  "${VENV_DIR}/bin/studyhub-rag" verify-isolation
)

if rg -n 'AgentOrchestrator|QueryPlanner|RouterConstraint|ToolLoopService' \
  "${AGENT_DIR}/src" "${AGENT_DIR}/training"; then
  printf 'Legacy Agent architecture symbol detected.\n' >&2
  exit 1
fi

printf 'StudyHub Agent Phase 1 verification passed.\n'
