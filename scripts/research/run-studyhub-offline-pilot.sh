#!/usr/bin/env bash
set -euo pipefail

# This wrapper deliberately unsets production/remote configuration and forces
# Hugging Face into local-files-only mode. It never starts a StudyHub service.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROVIDER="${1:-fixture-snapshot-guarded}"
RUN_NAME="${2:-snapshot-pilot}"
ARTIFACT_ROOT="${STUDYHUB_OFFLINE_PILOT_ROOT:-$ROOT_DIR/artifacts/agentic_platform/offline-pilot}"
RUN_ROOT="$ARTIFACT_ROOT/$RUN_NAME"

if [[ "$PROVIDER" == local-qwen* ]]; then
  PYTHON_BIN="${STUDYHUB_OFFLINE_PILOT_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
  BACKEND_DEPS_PYTHON="${STUDYHUB_BACKEND_DEPS_PYTHON:-/data/chengjin/studyhub/backend/.venv/bin/python}"
  BACKEND_SITE="$($BACKEND_DEPS_PYTHON -c 'import site; print(site.getsitepackages()[0])')"
  export PYTHONPATH="$BACKEND_SITE"
else
  PYTHON_BIN="${STUDYHUB_OFFLINE_PILOT_PYTHON:-/data/chengjin/studyhub/backend/.venv/bin/python}"
  unset PYTHONPATH
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset ANTHROPIC_BASE_URL OPENAI_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-pilot"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export STUDYHUB_OFFLINE_PILOT_SOURCE_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"

MANIFEST="$($PYTHON_BIN "$ROOT_DIR/scripts/research/build-agentic-pilot-manifest.py" \
  --run-name "$RUN_NAME" \
  --artifact-root "$ARTIFACT_ROOT")"

exec "$PYTHON_BIN" "$ROOT_DIR/scripts/research/run-agentic-pilot.py" \
  --scenario-manifest "$MANIFEST" \
  --count "${STUDYHUB_OFFLINE_PILOT_COUNT:-100}" \
  --concurrency "${STUDYHUB_OFFLINE_PILOT_CONCURRENCY:-8}" \
  --provider "$PROVIDER" \
  --output-dir "$RUN_ROOT/output"
