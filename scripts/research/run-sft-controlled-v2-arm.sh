#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${STUDYHUB_SFT_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"

if (( $# < 3 || $# > 4 )); then
  echo "usage: $0 EXPERIMENT_ID SEED GPU [--evaluate-only|--train-only]" >&2
  exit 2
fi

cd "$ROOT_DIR"
export PYTHONPATH="backend:.${PYTHONPATH:+:$PYTHONPATH}"

args=(
  -m ml.agentic_platform.sft.controlled_v2.run
  --experiment-id "$1"
  --seed "$2"
  --gpu "$3"
)
if (( $# == 4 )); then
  args+=("$4")
fi
"$PYTHON" "${args[@]}"
