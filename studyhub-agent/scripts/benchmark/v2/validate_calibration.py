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


def validate_common(record: dict[str, Any], manifest: dict[str, Any], manifest_path: Path) -> list[str]:
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
    return failures


def validate_gate(record: dict[str, Any], manifest: dict[str, Any], manifest_path: Path) -> list[str]:
    failures = validate_common(record, manifest, manifest_path)
    if record.get("coverage", {}).get("episodes_scored") != record.get("coverage", {}).get("episodes_expected"):
        failures.append("episode_coverage_incomplete")
    if record.get("coverage", {}).get("infra_excluded") != 0:
        failures.append("infra_excluded_nonzero")
    if record.get("request_audit", {}).get("violations") != 0:
        failures.append("prompt_cardinality_violation")
    if record.get("difficulty_annotation", {}).get("status") != "NOT_APPLIED_INSUFFICIENT_SAMPLE":
        failures.append("difficulty_claim_not_conservative")
    return failures


def validate_development_variance(record: dict[str, Any], manifest: dict[str, Any], manifest_path: Path) -> list[str]:
    failures = validate_common(record, manifest, manifest_path)
    development = record.get("development", {})
    variance = record.get("variance", {})
    development_tasks = int(manifest.get("counts", {}).get("development", 0))
    if development.get("episodes_expected") != development_tasks:
        failures.append("development_expected_count_mismatch")
    if development.get("episodes_scored") != development_tasks:
        failures.append("development_coverage_incomplete")
    if development.get("infra_excluded") != 0:
        failures.append("development_infra_excluded_nonzero")
    if development.get("working_tree_dirty") is not False:
        failures.append("development_worktree_not_clean")
    if development.get("request_audit", {}).get("violations") != 0:
        failures.append("development_prompt_cardinality_violation")
    tasks = int(variance.get("tasks_expected", 0))
    rollouts = int(variance.get("rollouts_per_task", 0))
    if tasks <= 0 or rollouts != 4:
        failures.append("variance_contract_invalid")
    if variance.get("tasks_complete") != tasks:
        failures.append("variance_group_coverage_incomplete")
    if variance.get("episodes_expected") != tasks * rollouts:
        failures.append("variance_expected_count_mismatch")
    if variance.get("episodes_scored") != tasks * rollouts:
        failures.append("variance_episode_coverage_incomplete")
    if variance.get("infra_excluded") != 0:
        failures.append("variance_infra_excluded_nonzero")
    if variance.get("working_tree_dirty") is True and not variance.get("dirty_scope"):
        failures.append("variance_dirty_worktree_not_disclosed")
    if variance.get("request_audit", {}).get("violations") != 0:
        failures.append("variance_prompt_cardinality_violation")
    if record.get("difficulty_annotation", {}).get("status") != "NOT_APPLIED":
        failures.append("difficulty_claim_not_conservative")
    if record.get("external_model_evaluations") != "NOT_RUN":
        failures.append("external_model_evaluation_claim_invalid")
    return failures


def validate(record: dict[str, Any], manifest: dict[str, Any], manifest_path: Path) -> list[str]:
    if "development" in record or "variance" in record:
        return validate_development_variance(record, manifest, manifest_path)
    return validate_gate(record, manifest, manifest_path)


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--record",
        type=Path,
        action="append",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=project / "benchmarks/studyhub-agent-v2/manifest.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    records = args.record or [
        Path(__file__).resolve().parents[3] / "docs/benchmark/evidence/qwen35-9b-base-gate-20260827.json",
        Path(__file__).resolve().parents[3]
        / "docs/benchmark/evidence/qwen35-9b-base-v2-development-variance-20260827.json",
    ]
    failures_by_record = {}
    for record_path in records:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        failures_by_record[str(record_path)] = validate(record, manifest, args.manifest)
    failures = [failure for values in failures_by_record.values() for failure in values]
    result = {
        "schema_version": "studyhub.agentbench-calibration-validation.v2",
        "status": "PASS" if not failures else "FAIL",
        "records": [str(path) for path in records],
        "manifest_sha256": sha256(args.manifest),
        "failures": failures_by_record,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
