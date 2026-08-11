#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ADAPTER_INPUT="${1:?usage: evaluate-router-production-contract.sh ADAPTER_OR_DASH OUTPUT_ROOT [raw|normalized|both] [bf16|nf4]}"
OUTPUT_ROOT="${2:?usage: evaluate-router-production-contract.sh ADAPTER_OR_DASH OUTPUT_ROOT [raw|normalized|both] [bf16|nf4]}"
MODE="${3:-both}"
PRECISION="${4:-bf16}"
GPU_ID="${STUDYHUB_SFT_GPU:-0}"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
BACKEND_PYTHON="${STUDYHUB_BACKEND_PYTHON:-$ROOT_DIR/backend/.venv/bin/python}"
DATASET="${STUDYHUB_ROUTER_DIAGNOSTIC_DATASET:-$ROOT_DIR/evaluation_artifacts/studyhub_agent/router_teacher_hidden_v1/router_hidden_300.jsonl}"
MODEL_PATH="${STUDYHUB_ROUTER_MODEL:-$ROOT_DIR/models/P0/Qwen3.5-2B}"
MAX_NEW_TOKENS="${STUDYHUB_ROUTER_EVAL_MAX_NEW_TOKENS:-1800}"

MODEL_PATH="$(realpath "$MODEL_PATH")"
if [[ "$ADAPTER_INPUT" == "-" ]]; then
  ADAPTER_PATH=""
  PREDICTIONS_NAME="base_predictions.jsonl"
else
  ADAPTER_PATH="$(realpath "$ADAPTER_INPUT")"
  PREDICTIONS_NAME="adapter_predictions.jsonl"
fi

if [[ "$MODE" != "raw" && "$MODE" != "normalized" && "$MODE" != "both" ]]; then
  echo "mode must be raw, normalized, or both: $MODE" >&2
  exit 2
fi
if [[ "$PRECISION" != "bf16" && "$PRECISION" != "nf4" ]]; then
  echo "precision must be bf16 or nf4: $PRECISION" >&2
  exit 2
fi
if [[ ! "$MAX_NEW_TOKENS" =~ ^[1-9][0-9]*$ ]]; then
  echo "STUDYHUB_ROUTER_EVAL_MAX_NEW_TOKENS must be a positive integer" >&2
  exit 2
fi
if [[ ! -d "$MODEL_PATH" || ! -f "$DATASET" ]]; then
  echo "model or diagnostic dataset is missing" >&2
  exit 2
fi
if [[ -n "$ADAPTER_PATH" && ! -f "$ADAPTER_PATH/adapter_model.safetensors" ]]; then
  echo "adapter is incomplete: $ADAPTER_PATH" >&2
  exit 2
fi

GPU_USED_MIB="$(
  nvidia-smi -i "$GPU_ID" --query-gpu=memory.used --format=csv,noheader,nounits \
    | tr -d ' '
)"
if (( GPU_USED_MIB > 1024 )); then
  echo "GPU $GPU_ID is not idle (${GPU_USED_MIB} MiB used); refusing to interfere" >&2
  exit 3
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset ANTHROPIC_BASE_URL OPENAI_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-sft-router-evaluation"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
QUANTIZATION_SITE="$ROOT_DIR/training_artifacts/studyhub_agent_sft/quantization_env/site-packages"
if [[ "$PRECISION" == "nf4" && ! -d "$QUANTIZATION_SITE/bitsandbytes" ]]; then
  echo "isolated bitsandbytes installation is missing: $QUANTIZATION_SITE" >&2
  exit 2
fi
if [[ "$PRECISION" == "nf4" ]]; then
  export PYTHONPATH="$QUANTIZATION_SITE:$ROOT_DIR/backend:$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
fi

run_evaluation() {
  local variant="$1"
  local output_dir="$OUTPUT_ROOT/$variant"
  local extra_args=()
  local model_args=(--model "$MODEL_PATH")
  if [[ -n "$ADAPTER_PATH" ]]; then
    model_args+=(--adapter "$ADAPTER_PATH")
  fi
  if [[ "$variant" == "normalized" ]]; then
    extra_args+=(--normalize-routing-state)
  fi
  mkdir -p "$output_dir"
  (
    cd "$ROOT_DIR"
    CUDA_VISIBLE_DEVICES="$GPU_ID" "$TRAIN_PYTHON" \
      -m ml.agentic_platform.sft.evaluate_router \
      "${model_args[@]}" \
      --dataset "$DATASET" \
      --splits hidden_test \
      --production-contract \
      --max-new-tokens "$MAX_NEW_TOKENS" \
      --precision "$PRECISION" \
      --output-dir "$output_dir" \
      "${extra_args[@]}"
  )
  "$BACKEND_PYTHON" - "$output_dir/$PREDICTIONS_NAME" "$output_dir/analysis.json" <<'PY'
import json
import sys
from pathlib import Path

from ml.agentic_platform.sft.analyze_teacher_hidden_eval import analyze_predictions

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
analysis = analyze_predictions(source)
destination.write_text(
    json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
}

case "$MODE" in
  raw)
    run_evaluation raw
    ;;
  normalized)
    run_evaluation normalized
    ;;
  both)
    run_evaluation raw
    run_evaluation normalized
    ;;
esac

"$BACKEND_PYTHON" - "$ROOT_DIR" "$MODEL_PATH" "$ADAPTER_PATH" "$DATASET" \
  "$OUTPUT_ROOT" "$MODE" "$PRECISION" "$MAX_NEW_TOKENS" <<'PY'
import hashlib
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
model = Path(sys.argv[2])
adapter = Path(sys.argv[3]) if sys.argv[3] else None
dataset = Path(sys.argv[4])
output_root = Path(sys.argv[5])
mode, precision, max_new_tokens = sys.argv[6:9]

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

manifest = {
    "schema_version": "studyhub.agent.router.production_diagnostic.v1",
    "model_path": str(model.resolve()),
    "adapter_path": str(adapter.resolve()) if adapter else None,
    "adapter_sha256": (
        sha256(adapter / "adapter_model.safetensors") if adapter else None
    ),
    "dataset_path": str(dataset.resolve()),
    "dataset_sha256": sha256(dataset),
    "git_commit": subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip(),
    "mode": mode,
    "precision": precision,
    "production_api_called": False,
    "production_database_accessed": False,
    "final_holdout_read": False,
    "decoding": {
        "do_sample": False,
        "max_new_tokens": int(max_new_tokens),
        "batch_size": 8,
    },
}
destination = output_root / "run_manifest.json"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
