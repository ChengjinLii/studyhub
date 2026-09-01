#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT_ROOT="${STUDYHUB_SFT2_ARTIFACT_ROOT:-${PROJECT_ROOT}}"
VENV_DIR="${STUDYHUB_TRAIN_VENV:-${ARTIFACT_ROOT}/.venv-train}"
BASE="${ARTIFACT_ROOT}/artifacts/areal/model-overlays/qwen35-4b-base-canonical-tokenizer"
CHECKPOINT_ROOT="${ARTIFACT_ROOT}/artifacts/areal/checkpoints/$(id -un)/studyhub-qwen35-4b-compact-sft2/qwen35-4b-sft2-compact-v1-formal-r32-seed-20260827"
COMPLETION_MARKER="${CHECKPOINT_ROOT}/QWEN35_4B_SFT2_COMPLETE.json"
OUTPUT="${STUDYHUB_SFT2_MERGED_MODEL:-${ARTIFACT_ROOT}/artifacts/areal/merged/qwen35-4b-sft2-compact-v1}"

if [[ -n "$(git -C "${PROJECT_ROOT}/.." status --porcelain)" ]]; then
  echo "M2 merge requires a clean Git worktree." >&2
  exit 4
fi
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Missing fixed training environment: ${VENV_DIR}" >&2
  exit 1
fi
if [[ ! -f "${COMPLETION_MARKER}" ]]; then
  echo "M2 completion marker is missing: ${COMPLETION_MARKER}" >&2
  exit 5
fi
if [[ -e "${OUTPUT}" ]]; then
  echo "Refusing to replace an existing M2 merged artifact: ${OUTPUT}" >&2
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
    raise SystemExit("M2 completion marker is not a completed formal run")
if value.get("expected_optimizer_updates") != 300 or value.get("final_global_step") != 299:
    raise SystemExit("M2 completion marker does not cover the frozen 300-update run")
recovery = value.get("recovery_checkpoint") or {}
if recovery.get("state_files", 0) < 1 or recovery.get("state_bytes", 0) < 1:
    raise SystemExit("M2 completion marker has no complete recovery inventory")
checkpoint = pathlib.Path(value["checkpoint"]["path"])
if not checkpoint.is_file():
    raise SystemExit(f"M2 adapter is missing: {checkpoint}")
digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
if digest != value["checkpoint"]["sha256"]:
    raise SystemExit("M2 adapter hash does not match the completion marker")
print(checkpoint.parent)
PY
)"

exec "${VENV_DIR}/bin/python" "${PROJECT_ROOT}/scripts/train/merge_sft_lora.py" \
  --base "${BASE}" \
  --adapter "${ADAPTER}" \
  --output "${OUTPUT}" \
  --stage sft2 \
  --completion-lineage "${COMPLETION_MARKER}"
