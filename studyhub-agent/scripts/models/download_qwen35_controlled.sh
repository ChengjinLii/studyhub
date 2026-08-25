#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_ROOT="$(cd "${PROJECT_ROOT}/.." && pwd)"
MODEL_ROOT="${STUDYHUB_MODEL_ROOT:-${REPO_ROOT}/models/P1}"
PROXY_URL="${STUDYHUB_DOWNLOAD_PROXY:-http://127.0.0.1:7892}"
TARGET="${1:-all}"

declare -Ar REPOSITORIES=(
  [4b]="Qwen/Qwen3.5-4B"
  [9b]="Qwen/Qwen3.5-9B"
)
declare -Ar REVISIONS=(
  [4b]="851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
  [9b]="c202236235762e1c871ad0ccb60c8ee5ba337b9a"
)
declare -Ar DIRECTORIES=(
  [4b]="Qwen3.5-4B"
  [9b]="Qwen3.5-9B"
)

if [[ "${PROXY_URL}" != "http://127.0.0.1:7892" ]]; then
  echo "Only http://127.0.0.1:7892 is allowed for this download." >&2
  exit 2
fi
if [[ "${TARGET}" != "4b" && "${TARGET}" != "9b" && "${TARGET}" != "all" && "${TARGET}" != "verify" ]]; then
  echo "Usage: $0 [4b|9b|all|verify]" >&2
  exit 2
fi
if ! command -v hf >/dev/null 2>&1; then
  echo "The Hugging Face CLI is missing: install huggingface_hub[cli]." >&2
  exit 1
fi

export HTTP_PROXY="${PROXY_URL}"
export HTTPS_PROXY="${PROXY_URL}"
export ALL_PROXY="${PROXY_URL}"
export http_proxy="${PROXY_URL}"
export https_proxy="${PROXY_URL}"
export all_proxy="${PROXY_URL}"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="${NO_PROXY}"

verify_model() {
  local size="$1"
  local model_dir="${MODEL_ROOT}/${DIRECTORIES[${size}]}"
  python3 - "${model_dir}" "${REPOSITORIES[${size}]}" "${REVISIONS[${size}]}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

model_dir = Path(sys.argv[1]).resolve()
repository = sys.argv[2]
revision = sys.argv[3]
index_path = model_dir / "model.safetensors.index.json"
config_path = model_dir / "config.json"
if not index_path.is_file() or not config_path.is_file():
    raise SystemExit(f"missing model index or config under {model_dir}")

index = json.loads(index_path.read_text(encoding="utf-8"))
shards = sorted(set(index.get("weight_map", {}).values()))
if not shards:
    raise SystemExit("model index contains no weight shards")
missing = [name for name in shards if not (model_dir / name).is_file()]
empty = [name for name in shards if (model_dir / name).is_file() and (model_dir / name).stat().st_size == 0]
if missing or empty:
    raise SystemExit(f"invalid shards: missing={missing}, empty={empty}")

config = json.loads(config_path.read_text(encoding="utf-8"))
if config.get("model_type") != "qwen3_5":
    raise SystemExit(f"unexpected model_type: {config.get('model_type')}")

manifest = {
    "schema_version": "studyhub.model-download.v1",
    "repository": repository,
    "revision": revision,
    "model_dir": str(model_dir),
    "weight_shards": [
        {"name": name, "bytes": (model_dir / name).stat().st_size} for name in shards
    ],
    "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
    "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
}
(model_dir / "studyhub_download_manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(manifest, ensure_ascii=False, indent=2))
PY
}

download_model() {
  local size="$1"
  local model_dir="${MODEL_ROOT}/${DIRECTORIES[${size}]}"
  mkdir -p "${model_dir}"
  hf download "${REPOSITORIES[${size}]}" \
    --repo-type model \
    --revision "${REVISIONS[${size}]}" \
    --local-dir "${model_dir}" \
    --max-workers "${HF_MAX_WORKERS:-2}"
  verify_model "${size}"
}

case "${TARGET}" in
  4b|9b) download_model "${TARGET}" ;;
  all)
    download_model 4b
    download_model 9b
    ;;
  verify)
    verify_model 4b
    verify_model 9b
    ;;
esac
