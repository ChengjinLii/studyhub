#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
ADAPTER_PATH="${1:?usage: evaluate-router-final-holdout.sh ADAPTER}"
MODEL_PATH="${STUDYHUB_ROUTER_MODEL:-$ROOT_DIR/models/P0/Qwen3.5-2B}"
HOLDOUT_DIR="$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_final_holdout_v2"
DATASET="$HOLDOUT_DIR/router_final_holdout_300.jsonl"
SEAL="$HOLDOUT_DIR/seal.json"
RESULTS_DIR="$HOLDOUT_DIR/results"
PREDICTIONS="$RESULTS_DIR/adapter_predictions.jsonl"
ANALYSIS="$RESULTS_DIR/analysis.json"
RECEIPT="$HOLDOUT_DIR/evaluation_receipt.json"
ACCESS_LOCK="$HOLDOUT_DIR/.evaluation_access_started.json"
GPU_ID="${STUDYHUB_SFT_GPU:-0}"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
BACKEND_PYTHON="${STUDYHUB_BACKEND_PYTHON:-$WORKSPACE_ROOT/backend/.venv/bin/python}"
MAX_NEW_TOKENS="${STUDYHUB_ROUTER_EVAL_MAX_NEW_TOKENS:-1800}"

MODEL_PATH="$(realpath "$MODEL_PATH")"
ADAPTER_PATH="$(realpath "$ADAPTER_PATH")"
if [[ "${STUDYHUB_ALLOW_SEALED_HOLDOUT:-0}" != "1" ]]; then
  echo "sealed holdout requires STUDYHUB_ALLOW_SEALED_HOLDOUT=1" >&2
  exit 4
fi
if [[ ! -d "$MODEL_PATH" || ! -f "$ADAPTER_PATH/adapter_model.safetensors" ]]; then
  echo "model or adapter is incomplete" >&2
  exit 2
fi
if [[ ! "$MAX_NEW_TOKENS" =~ ^[1-9][0-9]*$ ]]; then
  echo "STUDYHUB_ROUTER_EVAL_MAX_NEW_TOKENS must be a positive integer" >&2
  exit 2
fi
if [[ ! -f "$DATASET" || ! -f "$SEAL" ]]; then
  echo "sealed dataset or seal is missing" >&2
  exit 2
fi
if [[ -e "$RECEIPT" || -e "$PREDICTIONS" || -e "$ACCESS_LOCK" ]]; then
  echo "final holdout was already started or evaluated; refusing repeat access" >&2
  exit 5
fi

GPU_USED_MIB="$(
  nvidia-smi -i "$GPU_ID" --query-gpu=memory.used --format=csv,noheader,nounits \
    | tr -d ' '
)"
if (( GPU_USED_MIB > 1024 )); then
  echo "GPU $GPU_ID is not idle (${GPU_USED_MIB} MiB used); refusing to interfere" >&2
  exit 3
fi

"$BACKEND_PYTHON" - "$ACCESS_LOCK" "$DATASET" "$ADAPTER_PATH" \
  "$MAX_NEW_TOKENS" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

lock, dataset, adapter = map(Path, sys.argv[1:4])
payload = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "dataset": str(dataset),
    "adapter": str(adapter),
    "max_new_tokens": int(sys.argv[4]),
    "single_use": True,
}
descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
PY

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset ANTHROPIC_BASE_URL OPENAI_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-sft-router-final-holdout"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTHONPATH="$WORKSPACE_ROOT/backend:$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$RESULTS_DIR"

CUDA_VISIBLE_DEVICES="$GPU_ID" "$TRAIN_PYTHON" \
  -m ml.agentic_platform.sft.evaluate_router \
  --model "$MODEL_PATH" \
  --adapter "$ADAPTER_PATH" \
  --dataset "$DATASET" \
  --splits final_holdout_v2 \
  --production-contract \
  --max-new-tokens "$MAX_NEW_TOKENS" \
  --precision bf16 \
  --output-dir "$RESULTS_DIR"

"$BACKEND_PYTHON" - "$PREDICTIONS" "$ANALYSIS" <<'PY'
import json
import sys
from pathlib import Path

from ml.agentic_platform.sft.analyze_teacher_hidden_eval import analyze_predictions

source, destination = map(Path, sys.argv[1:])
destination.write_text(
    json.dumps(
        analyze_predictions(source),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)
PY

"$BACKEND_PYTHON" -m ml.agentic_platform.sft.record_final_holdout_evaluation \
  --adapter "$ADAPTER_PATH" \
  --predictions "$PREDICTIONS" \
  --dataset "$DATASET" \
  --seal "$SEAL" \
  --receipt "$RECEIPT"

"$BACKEND_PYTHON" - "$ANALYSIS" "$HOLDOUT_DIR/final_gate.json" <<'PY'
import json
import sys
from pathlib import Path

from ml.agentic_platform.sft.gate_router_production_diagnostic import gate_analysis

source, destination = map(Path, sys.argv[1:])
result = {
    "schema_version": "studyhub.agent.router.final_gate.v1",
    "selection_dataset": "sealed_holdout_single_use",
    "evaluation_count": 1,
    **gate_analysis(json.loads(source.read_text(encoding="utf-8"))),
}
destination.write_text(
    json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
PY
