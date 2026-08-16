#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${STUDYHUB_BACKEND_PYTHON:-$ROOT_DIR/backend/.venv/bin/python}"
ARTIFACT_ROOT="$ROOT_DIR/training_artifacts/studyhub_agent_rl/router_rl_maturity_v2"
EVAL_ROOT="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_rl_maturity_v2"

cd "$ROOT_DIR"
PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR" "$PYTHON" \
  -m ml.agentic_platform.rl.maturity_v2.report \
  --repo-root "$ROOT_DIR" \
  --artifact-root "$ARTIFACT_ROOT" \
  --evaluation-root "$EVAL_ROOT" \
  --coverage "$EVAL_ROOT/gate/knowledge_coverage.json" \
  --output "$ROOT_DIR/reports/recagent/agentic-platform/STUDYHUB_ROUTER_RL_MATURITY_V2_REPORT.html"
