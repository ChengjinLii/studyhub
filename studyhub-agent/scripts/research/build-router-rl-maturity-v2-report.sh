#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
PYTHON="${STUDYHUB_BACKEND_PYTHON:-$WORKSPACE_ROOT/backend/.venv/bin/python}"
ARTIFACT_ROOT="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_rl_maturity_v2"
EVAL_ROOT="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_maturity_v2"

cd "$ROOT_DIR"
PYTHONPATH="$WORKSPACE_ROOT/backend:$ROOT_DIR" "$PYTHON" \
  -m ml.agentic_platform.rl.maturity_v2.report \
  --repo-root "$ROOT_DIR" \
  --artifact-root "$ARTIFACT_ROOT" \
  --evaluation-root "$EVAL_ROOT" \
  --coverage "$EVAL_ROOT/gate/knowledge_coverage.json" \
  --output "$ROOT_DIR/reports/STUDYHUB_ROUTER_RL_MATURITY_V2_REPORT.html"
