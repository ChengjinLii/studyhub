#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
RUFF_BIN="${RUFF_BIN:-$PROJECT_ROOT/.venv/bin/ruff}"
PYTEST_BIN="${PYTEST_BIN:-$PROJECT_ROOT/.venv/bin/pytest}"

for executable in "$PYTHON_BIN" "$RUFF_BIN" "$PYTEST_BIN"; do
  if [[ ! -x "$executable" ]]; then
    printf 'missing required executable: %s\n' "$executable" >&2
    exit 2
  fi
done

if [[ -z "${BUILDER_COMMIT:-}" && -f "benchmarks/studyhub-agent-v2/manifest.json" ]]; then
  BUILDER_COMMIT="$("$PYTHON_BIN" - "benchmarks/studyhub-agent-v2/manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if manifest.get("status") == "FROZEN_FOR_BASELINE":
    print(manifest.get("builder_commit", ""))
PY
)"
fi
# An interrupted rebuild leaves the worktree manifest in candidate state. Recover
# the last frozen builder from Git instead of silently rebinding the benchmark to HEAD.
if [[ -z "${BUILDER_COMMIT:-}" ]]; then
  REPO_ROOT="$(git rev-parse --show-toplevel)"
  MANIFEST_REL="$(realpath --relative-to="$REPO_ROOT" "$PROJECT_ROOT/benchmarks/studyhub-agent-v2/manifest.json")"
  BUILDER_COMMIT="$(git show "HEAD:${MANIFEST_REL}" 2>/dev/null | "$PYTHON_BIN" -c '
import json
import sys

try:
    manifest = json.load(sys.stdin)
except (json.JSONDecodeError, OSError):
    manifest = {}
if manifest.get("status") == "FROZEN_FOR_BASELINE":
    print(manifest.get("builder_commit", ""))
' || true)"
fi
BUILDER_COMMIT="${BUILDER_COMMIT:-$(git rev-parse HEAD)}"
if ! git cat-file -e "${BUILDER_COMMIT}^{commit}"; then
  printf 'invalid builder commit: %s\n' "$BUILDER_COMMIT" >&2
  exit 2
fi
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git show -s --format=%ct "$BUILDER_COMMIT")}"

required_inputs=(
  "ai_platform/rag_experiments/artifacts/corpus/chunks.jsonl"
  "../backup/oss_materials/metadata/materials.json"
)
for input in "${required_inputs[@]}"; do
  if [[ ! -f "$input" ]]; then
    printf 'missing authorized local benchmark input: %s\n' "$input" >&2
    printf 'StudyHub OCR/source snapshots are intentionally not redistributed in Git.\n' >&2
    exit 2
  fi
done

export PYTHONPATH="$PROJECT_ROOT/src:$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

if [[ -f "artifacts/benchmark-v2/web-snapshots/snapshot.jsonl" ]]; then
  "$PYTHON_BIN" scripts/benchmark/v2/fetch_web_snapshots.py --offline
else
  "$PYTHON_BIN" scripts/benchmark/v2/fetch_web_snapshots.py
fi

external_cache_ready=true
while IFS= read -r source_path; do
  if [[ -n "$source_path" && ! -d "$source_path" ]]; then
    external_cache_ready=false
  fi
done < <("$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

lock = json.loads(Path("external_benchmarks/lock.json").read_text(encoding="utf-8"))
for row in lock["benchmarks"].values():
    if row.get("source_exported"):
        print(row["source_path"])
PY
)
if [[ "$external_cache_ready" == true ]]; then
  "$PYTHON_BIN" scripts/benchmark/external/fetch.py --benchmark all --offline
else
  "$PYTHON_BIN" scripts/benchmark/external/fetch.py --benchmark all
fi

"$PYTHON_BIN" scripts/benchmark/v2/build.py
"$PYTHON_BIN" scripts/benchmark/v2/audit_v1_semantics.py
"$PYTHON_BIN" scripts/benchmark/v2/audit.py
"$PYTHON_BIN" scripts/benchmark/v2/audit_semantic_diversity.py
"$PYTHON_BIN" scripts/benchmark/v2/self_test.py
"$PYTHON_BIN" scripts/benchmark/v2/run_challenge_suite.py
"$PYTHON_BIN" scripts/benchmark/v2/generate_review_packs.py
"$PYTHON_BIN" scripts/benchmark/external/validate_registry.py
"$PYTHON_BIN" scripts/benchmark/external/smoke.py
calibration_contract_test="tests/unit/benchmark_v2/test_contracts.py::test_development_and_variance_evidence_is_bound_and_complete"
"$PYTEST_BIN" \
  tests/unit/benchmark_v1 \
  tests/unit/benchmark_v2 \
  tests/unit/external_benchmarks \
  --deselect "$calibration_contract_test"
"$RUFF_BIN" check src/studyhub_agent/benchmark_v2 scripts/benchmark/v2 scripts/benchmark/external external_benchmarks tests/unit/benchmark_v2 tests/unit/external_benchmarks
"$RUFF_BIN" format --check src/studyhub_agent/benchmark_v2 scripts/benchmark/v2 scripts/benchmark/external external_benchmarks tests/unit/benchmark_v2 tests/unit/external_benchmarks
"$PYTHON_BIN" scripts/benchmark/secret_scan.py
"$PYTHON_BIN" scripts/benchmark/v2/finalize.py --builder-commit "$BUILDER_COMMIT"
"$PYTHON_BIN" scripts/benchmark/v2/generate_docs.py
"$PYTHON_BIN" scripts/benchmark/v2/validate_manifest.py --require-frozen --include-hidden
"$PYTHON_BIN" scripts/benchmark/v2/validate_calibration.py
"$PYTEST_BIN" "$calibration_contract_test"

printf 'StudyHub AgentBench v2 quality gate passed for builder commit %s\n' "$BUILDER_COMMIT"
