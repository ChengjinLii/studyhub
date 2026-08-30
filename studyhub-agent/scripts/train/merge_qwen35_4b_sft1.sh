#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv-train"
BASE="${PROJECT_ROOT}/artifacts/areal/model-overlays/qwen35-4b-base-canonical-tokenizer"
CHECKPOINT_ROOT="${PROJECT_ROOT}/artifacts/areal/checkpoints/$(id -un)/studyhub-qwen35-4b-open-agentic-sft1/qwen35-4b-sft1-formal-r32-seed-20260827"
COMPLETION_MARKER="${CHECKPOINT_ROOT}/QWEN35_4B_SFT1_COMPLETE.json"
OUTPUT="${STUDYHUB_SFT1_MERGED_MODEL:-${PROJECT_ROOT}/artifacts/areal/merged/qwen35-4b-sft1-r32-seed-20260827}"

if [[ -n "$(git -C "${PROJECT_ROOT}/.." status --porcelain)" ]]; then
  echo "M1 merge requires a clean Git worktree." >&2
  exit 4
fi
if [[ ! -f "${COMPLETION_MARKER}" ]]; then
  echo "M1 completion marker is missing: ${COMPLETION_MARKER}" >&2
  exit 5
fi
if [[ -e "${OUTPUT}" ]]; then
  echo "Refusing to replace an existing M1 merged artifact: ${OUTPUT}" >&2
  exit 6
fi

ADAPTER="$(${VENV_DIR}/bin/python -S - "${COMPLETION_MARKER}" <<'PY'
import hashlib
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
value = json.loads(path.read_text(encoding="utf-8"))
if value.get("status") != "COMPLETE" or value.get("mode") != "formal":
    raise SystemExit("M1 completion marker is not a completed formal run")
if value.get("expected_optimizer_updates") != 2100 or value.get("final_global_step") != 2099:
    raise SystemExit("M1 completion marker does not cover the frozen 2100-update run")
checkpoint = pathlib.Path(value["checkpoint"]["path"])
if not checkpoint.is_file():
    raise SystemExit(f"M1 adapter is missing: {checkpoint}")
digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
if digest != value["checkpoint"]["sha256"]:
    raise SystemExit("M1 adapter hash does not match the completion marker")
print(checkpoint.parent)
PY
)"

exec "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/merge_sft_lora.py" \
  --base "${BASE}" \
  --adapter "${ADAPTER}" \
  --output "${OUTPUT}" \
  --stage sft1 \
  --completion-lineage "${COMPLETION_MARKER}"
