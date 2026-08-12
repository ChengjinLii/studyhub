#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${STUDYHUB_BACKEND_PYTHON:-$ROOT_DIR/backend/.venv/bin/python}"
ARTIFACT_ROOT="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_rl_maturity_v2"

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-router-rl-maturity-v2-action-audit"

cd "$ROOT_DIR"
PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$PYTHON" \
  -m ml.agentic_platform.rl.maturity_v2.action_audit \
  --train "$ARTIFACT_ROOT/train.jsonl" \
  --validation "$ARTIFACT_ROOT/validation.jsonl" \
  --output "$ARTIFACT_ROOT/action_space_audit.json"
