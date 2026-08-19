#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
PYTHON="${STUDYHUB_BACKEND_PYTHON:-$WORKSPACE_ROOT/backend/.venv/bin/python}"
POLICY="${1:-rule}"
SPLIT="${2:-validation}"
LABEL="${3:-${POLICY}-${SPLIT}}"
OUTPUT_DIR="$ROOT_DIR/evaluation_artifacts/studyhub_agent/web_router_v1/$LABEL"

if [[ "$POLICY" != "rule" && "$POLICY" != "openai-compatible" && "$POLICY" != "local-hf" ]]; then
  echo "policy must be rule, openai-compatible, or local-hf" >&2
  exit 2
fi
if [[ "$SPLIT" != "all" && "$SPLIT" != "train" && "$SPLIT" != "validation" && "$SPLIT" != "test" ]]; then
  echo "split must be all, train, validation, or test" >&2
  exit 2
fi
if [[ -e "$OUTPUT_DIR" ]]; then
  echo "evaluation output already exists: $OUTPUT_DIR" >&2
  exit 3
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
export STUDYHUB_ENVIRONMENT="offline-web-router-evaluation"
export PYTHONPATH="$WORKSPACE_ROOT/backend:$ROOT_DIR"

ARGS=(
  --policy "$POLICY"
  --split "$SPLIT"
  --output-dir "$OUTPUT_DIR"
)
if [[ "$POLICY" == "openai-compatible" ]]; then
  ARGS+=(--concurrency "${STUDYHUB_WEB_ROUTER_EVAL_CONCURRENCY:-2}")
fi
if [[ "$POLICY" == "local-hf" ]]; then
  PYTHON="${STUDYHUB_ML_PYTHON:-$ROOT_DIR/../LLaMA-Factory/.venv/bin/python}"
  BACKEND_SITE_PACKAGES="$($WORKSPACE_ROOT/backend/.venv/bin/python -c 'import site; print(site.getsitepackages()[0])')"
  export PYTHONPATH="$BACKEND_SITE_PACKAGES:$PYTHONPATH"
  unset OPENAI_BASE_URL ANTHROPIC_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
  unset STUDYHUB_WEB_ROUTER_EVAL_MODEL_BASE_URL
  export HF_HUB_OFFLINE=1
  export TRANSFORMERS_OFFLINE=1
  ARGS+=(
    --local-model "${STUDYHUB_WEB_ROUTER_EVAL_LOCAL_MODEL:-$ROOT_DIR/models/P0/Qwen3.5-2B}"
    --local-batch-size "${STUDYHUB_WEB_ROUTER_EVAL_BATCH_SIZE:-4}"
    --local-max-new-tokens "${STUDYHUB_WEB_ROUTER_EVAL_MAX_NEW_TOKENS:-512}"
    --local-device "${STUDYHUB_WEB_ROUTER_EVAL_DEVICE:-cuda}"
  )
  if [[ -n "${STUDYHUB_WEB_ROUTER_EVAL_LOCAL_ADAPTER:-}" ]]; then
    ARGS+=(--local-adapter "$STUDYHUB_WEB_ROUTER_EVAL_LOCAL_ADAPTER")
  fi
fi

cd "$ROOT_DIR"
"$PYTHON" -m ml.agentic_platform.web_research.evaluate "${ARGS[@]}"
