#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${STUDYHUB_SFT_PYTHON:-/data/chengjin/LLaMA-Factory/.venv/bin/python}"

cd "$ROOT_DIR"
export PYTHONPATH="backend:.${PYTHONPATH:+:$PYTHONPATH}"

PREREG="$ROOT_DIR/evaluation_artifacts/studyhub_agent/sft_controlled_v2/contract/pre_registration.json"
if [[ ! -f "$PREREG" ]]; then
  "$PYTHON" -m ml.agentic_platform.sft.controlled_v2.prepare
else
  echo "frozen pre-registration exists; preserving it: $PREREG"
fi
"$PYTHON" -m ml.agentic_platform.sft.controlled_v2.variants all
"$PYTHON" -m ml.agentic_platform.sft.controlled_v2.audit
"$PYTHON" -m ml.agentic_platform.sft.controlled_v2.configs --initial
