#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE_MODEL="${1:?usage: export-merged-sft-adapter.sh BASE_MODEL ADAPTER OUTPUT_DIR [TEMPLATE]}"
ADAPTER_PATH="${2:?usage: export-merged-sft-adapter.sh BASE_MODEL ADAPTER OUTPUT_DIR [TEMPLATE]}"
OUTPUT_DIR="${3:?usage: export-merged-sft-adapter.sh BASE_MODEL ADAPTER OUTPUT_DIR [TEMPLATE]}"
TEMPLATE="${4:-qwen3_5_nothink}"
CLI="${STUDYHUB_LLAMFACTORY_CLI:-/data/chengjin/LLaMA-Factory/.venv/bin/llamafactory-cli}"

BASE_MODEL="$(realpath "$BASE_MODEL")"
ADAPTER_PATH="$(realpath "$ADAPTER_PATH")"
if [[ -e "$OUTPUT_DIR" ]]; then
  echo "refusing to overwrite existing export: $OUTPUT_DIR" >&2
  exit 2
fi
if [[ ! -d "$BASE_MODEL" || ! -f "$ADAPTER_PATH/adapter_model.safetensors" ]]; then
  echo "base model or adapter is incomplete" >&2
  exit 2
fi

unset DATABASE_URL MYSQL_URL STUDYHUB_DATABASE_URL
unset ANTHROPIC_BASE_URL OPENAI_BASE_URL STUDYHUB_AGENTIC_MODEL_BASE_URL
export STUDYHUB_ENVIRONMENT="offline-sft-export"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

CONFIG_PATH="$(mktemp --suffix=.yaml)"
trap 'rm -f "$CONFIG_PATH"' EXIT
cat > "$CONFIG_PATH" <<EOF
model_name_or_path: $BASE_MODEL
adapter_name_or_path: $ADAPTER_PATH
template: $TEMPLATE
trust_remote_code: true
finetuning_type: lora
export_dir: $OUTPUT_DIR
export_size: 5
export_device: cpu
export_legacy_format: false
EOF

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$CLI" export "$CONFIG_PATH"
FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

python3 - "$ROOT_DIR" "$BASE_MODEL" "$ADAPTER_PATH" "$OUTPUT_DIR" \
  "$TEMPLATE" "$STARTED_AT" "$FINISHED_AT" <<'PY'
import hashlib
import json
import subprocess
import sys
from pathlib import Path

root, base, adapter, output = map(Path, sys.argv[1:5])
template, started_at, finished_at = sys.argv[5:]

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

files = {}
for path in sorted(item for item in output.rglob("*") if item.is_file()):
    files[str(path.relative_to(output))] = {
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }
aggregate = hashlib.sha256(
    json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
manifest = {
    "schema_version": "studyhub.agent.sft.merged_export.v1",
    "base_model": str(base),
    "adapter": str(adapter),
    "adapter_sha256": sha256(adapter / "adapter_model.safetensors"),
    "output": str(output),
    "template": template,
    "started_at": started_at,
    "finished_at": finished_at,
    "git_commit": subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip(),
    "aggregate_sha256": aggregate,
    "files": files,
    "production_api_called": False,
    "production_database_accessed": False,
}
(output / "studyhub_export_manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
