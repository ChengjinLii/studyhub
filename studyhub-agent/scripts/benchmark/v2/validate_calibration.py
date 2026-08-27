#!/usr/bin/env python3
"""Validate a public calibration record against the finalized benchmark manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(record: dict[str, Any], manifest: dict[str, Any], manifest_path: Path) -> list[str]:
    failures = []
    if manifest.get("status") != "FROZEN_FOR_BASELINE":
        failures.append("benchmark_not_frozen")
    if record.get("benchmark_version") != manifest.get("benchmark_version"):
        failures.append("benchmark_version_mismatch")
    if record.get("benchmark_revision") != manifest.get("benchmark_revision"):
        failures.append("benchmark_revision_mismatch")
    if record.get("builder_commit") != manifest.get("builder_commit"):
        failures.append("builder_commit_mismatch")
    if record.get("benchmark_manifest_sha256") != sha256(manifest_path):
        failures.append("manifest_sha256_mismatch")
    if record.get("sealed_tasks_or_graders_used") is not False:
        failures.append("sealed_usage_not_false")
    if record.get("runtime", {}).get("optimizer_steps") != 0:
        failures.append("optimizer_steps_not_zero")
    if record.get("coverage", {}).get("episodes_scored") != record.get("coverage", {}).get("episodes_expected"):
        failures.append("episode_coverage_incomplete")
    if record.get("coverage", {}).get("infra_excluded") != 0:
        failures.append("infra_excluded_nonzero")
    if record.get("request_audit", {}).get("violations") != 0:
        failures.append("prompt_cardinality_violation")
    if record.get("difficulty_annotation", {}).get("status") != "NOT_APPLIED_INSUFFICIENT_SAMPLE":
        failures.append("difficulty_claim_not_conservative")
    return failures


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--record",
        type=Path,
        default=project / "docs/benchmark/evidence/qwen35-9b-base-gate-20260827.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=project / "benchmarks/studyhub-agent-v2/manifest.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    record = json.loads(args.record.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    failures = validate(record, manifest, args.manifest)
    result = {
        "schema_version": "studyhub.agentbench-calibration-validation.v2",
        "status": "PASS" if not failures else "FAIL",
        "record": str(args.record),
        "manifest_sha256": sha256(args.manifest),
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
