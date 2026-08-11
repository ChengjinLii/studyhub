#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODEL_PATH="${1:?usage: evaluate-grounded-tutor.sh MODEL ADAPTER_OR_DASH DATASET OUTPUT_DIR [validation|test] [bf16|nf4]}"
ADAPTER_INPUT="${2:?usage: evaluate-grounded-tutor.sh MODEL ADAPTER_OR_DASH DATASET OUTPUT_DIR [validation|test] [bf16|nf4]}"
DATASET="${3:?usage: evaluate-grounded-tutor.sh MODEL ADAPTER_OR_DASH DATASET OUTPUT_DIR [validation|test] [bf16|nf4]}"
OUTPUT_DIR="${4:?usage: evaluate-grounded-tutor.sh MODEL ADAPTER_OR_DASH DATASET OUTPUT_DIR [validation|test] [bf16|nf4]}"
SPLIT="${5:-validation}"
PRECISION="${6:-bf16}"
GPU_ID="${STUDYHUB_SFT_GPU:-1}"
TRAIN_PYTHON="${STUDYHUB_TRAIN_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"
BACKEND_PYTHON="${STUDYHUB_BACKEND_PYTHON:-$ROOT_DIR/backend/.venv/bin/python}"
BATCH_SIZE="${STUDYHUB_TUTOR_EVAL_BATCH_SIZE:-8}"
MAX_NEW_TOKENS="${STUDYHUB_TUTOR_EVAL_MAX_NEW_TOKENS:-512}"

MODEL_PATH="$(realpath "$MODEL_PATH")"
DATASET="$(realpath "$DATASET")"
if [[ "$ADAPTER_INPUT" == "-" ]]; then
  ADAPTER_PATH=""
  SUMMARY_NAME="base_summary.json"
else
  ADAPTER_PATH="$(realpath "$ADAPTER_INPUT")"
  SUMMARY_NAME="adapter_summary.json"
fi
if [[ "$SPLIT" != "validation" && "$SPLIT" != "test" ]]; then
  echo "split must be validation or test: $SPLIT" >&2
  exit 2
fi
if [[ "$PRECISION" != "bf16" && "$PRECISION" != "nf4" ]]; then
  echo "precision must be bf16 or nf4: $PRECISION" >&2
  exit 2
fi
if [[ ! -d "$MODEL_PATH" || ! -f "$DATASET" ]]; then
  echo "model or dataset is missing" >&2
  exit 2
fi
if [[ -n "$ADAPTER_PATH" && ! -f "$ADAPTER_PATH/adapter_model.safetensors" ]]; then
  echo "adapter is incomplete: $ADAPTER_PATH" >&2
  exit 2
fi
if [[ -e "$OUTPUT_DIR" ]]; then
  echo "refusing to overwrite evaluation output: $OUTPUT_DIR" >&2
  exit 2
fi

QUANTIZATION_SITE="$ROOT_DIR/training_artifacts/studyhub_agent_sft/quantization_env/site-packages"
if [[ "$PRECISION" == "nf4" && ! -d "$QUANTIZATION_SITE/bitsandbytes" ]]; then
  echo "isolated bitsandbytes installation is missing: $QUANTIZATION_SITE" >&2
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

if [[ "$SPLIT" == "test" ]]; then
  if [[ "${STUDYHUB_ALLOW_SEALED_HOLDOUT:-0}" != "1" ]]; then
    echo "sealed holdout requires STUDYHUB_ALLOW_SEALED_HOLDOUT=1" >&2
    exit 4
  fi
  HOLDOUT_LOCK="$(dirname "$DATASET")/.sealed_holdout_access.json"
  "$BACKEND_PYTHON" - "$HOLDOUT_LOCK" "$DATASET" "$OUTPUT_DIR" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

lock, dataset, output = map(Path, sys.argv[1:])
lock.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "accessed_at": datetime.now(timezone.utc).isoformat(),
    "dataset": str(dataset),
    "output": str(output),
    "single_use": True,
}
descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
PY
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset ANTHROPIC_BASE_URL OPENAI_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-sft-grounded-tutor-evaluation"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
if [[ "$PRECISION" == "nf4" ]]; then
  export PYTHONPATH="$QUANTIZATION_SITE:$ROOT_DIR/backend:$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="$ROOT_DIR/backend:$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
fi

ARGS=(
  --model "$MODEL_PATH"
  --dataset "$DATASET"
  --output-dir "$OUTPUT_DIR"
  --splits "$SPLIT"
  --precision "$PRECISION"
  --batch-size "$BATCH_SIZE"
  --max-new-tokens "$MAX_NEW_TOKENS"
)
if [[ -n "$ADAPTER_PATH" ]]; then
  ARGS+=(--adapter "$ADAPTER_PATH")
fi
CUDA_VISIBLE_DEVICES="$GPU_ID" "$TRAIN_PYTHON" \
  -m ml.agentic_platform.sft.evaluate_grounded_tutor "${ARGS[@]}"

"$BACKEND_PYTHON" -m ml.agentic_platform.sft.gate_grounded_tutor \
  --summary "$OUTPUT_DIR/$SUMMARY_NAME" \
  --expected-split "$SPLIT"

"$BACKEND_PYTHON" - "$ROOT_DIR" "$MODEL_PATH" "$ADAPTER_PATH" "$DATASET" \
  "$OUTPUT_DIR" "$SPLIT" "$PRECISION" <<'PY'
import hashlib
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
model = Path(sys.argv[2])
adapter = Path(sys.argv[3]) if sys.argv[3] else None
dataset = Path(sys.argv[4])
output = Path(sys.argv[5])
split, precision = sys.argv[6:8]

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

manifest = {
    "schema_version": "studyhub.agent.grounded_tutor.eval_run.v1",
    "model_path": str(model),
    "adapter_path": str(adapter) if adapter else None,
    "adapter_sha256": (
        sha256(adapter / "adapter_model.safetensors") if adapter else None
    ),
    "dataset_path": str(dataset),
    "dataset_sha256": sha256(dataset),
    "split": split,
    "precision": precision,
    "git_commit": subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip(),
    "production_api_called": False,
    "production_database_accessed": False,
}
(output / "run_manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
