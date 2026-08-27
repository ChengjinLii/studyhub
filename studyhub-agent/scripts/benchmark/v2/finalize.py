#!/usr/bin/env python3
"""Freeze AgentBench v2 only when every engineering quality gate passes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from external_benchmarks.registry import load_registry  # noqa: E402 - standalone script bootstraps project root


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def git_head(project: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def resolve_commit(project: Path, value: str) -> str:
    resolved = subprocess.run(
        ["git", "rev-parse", f"{value}^{{commit}}"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if len(resolved) != 40:
        raise RuntimeError(f"could not resolve builder commit: {value}")
    return resolved


def record(checks: list[dict[str, Any]], name: str, passed: bool, detail: Any) -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=project)
    parser.add_argument("--public-root", type=Path, default=project / "benchmarks/studyhub-agent-v2")
    parser.add_argument("--hidden-root", type=Path, default=project / "artifacts/benchmark-v2/studyhub-agent-v2")
    parser.add_argument(
        "--builder-commit",
        help="Commit containing the benchmark implementation; defaults to the current HEAD.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project = args.project.resolve()
    public_root = args.public_root.resolve()
    hidden_root = args.hidden_root.resolve()
    manifest_path = public_root / "manifest.json"
    manifest = read_json(manifest_path)
    structural = read_json(public_root / "structural-audit-summary.json")
    semantic = read_json(public_root / "semantic-audit-summary.json")
    self_test = read_json(public_root / "self-test-summary.json")
    challenge = read_json(public_root / "evaluator-challenge-summary.json")
    review = read_json(public_root / "review-pack-manifest.json")
    external_lock_path = project / "external_benchmarks/lock.json"
    external_lock = read_json(external_lock_path)
    external_smoke_path = project / "external_benchmarks/smoke-status.json"
    external_smoke = read_json(external_smoke_path)
    registry = load_registry(project / "external_benchmarks/registry.yaml")
    v1_lock = read_json(project / "configs/benchmark-v1-frozen-hashes.json")
    checks: list[dict[str, Any]] = []

    record(checks, "structural_audit", structural.get("status") == "PASS", structural.get("summary"))
    semantic_checks = semantic.get("checks", {})
    record(
        checks,
        "semantic_diversity",
        semantic.get("status") == "PASS" and all(semantic_checks.values()),
        semantic_checks,
    )
    dev = semantic.get("development", {})
    largest = float(dev.get("largest_cluster_share", 1.0))
    record(checks, "development_largest_cluster_at_most_two_percent", largest <= 0.02, largest)
    oracle = self_test.get("oracle", {})
    record(
        checks,
        "oracle_reachability_at_least_99_percent",
        self_test.get("status") == "PASS" and float(oracle.get("pass_rate", 0.0)) >= 0.99,
        oracle,
    )
    negatives = self_test.get("negative_controls", {})
    record(
        checks,
        "negative_controls_reject_shortcuts",
        bool(negatives) and all(int(row.get("strict_pass", -1)) == 0 for row in negatives.values()),
        negatives,
    )
    metamorphic = self_test.get("metamorphic", {})
    record(
        checks,
        "metamorphic_tests",
        int(metamorphic.get("cases", 0)) > 0 and metamorphic.get("passed") == metamorphic.get("cases"),
        metamorphic,
    )
    shortcut = self_test.get("shortcut", {}).get("checks", {})
    record(checks, "shortcut_probes", bool(shortcut) and all(shortcut.values()), shortcut)
    record(
        checks,
        "evaluator_challenge_suite",
        challenge.get("status") == "PASS" and challenge.get("cases") == challenge.get("passed"),
        {"cases": challenge.get("cases"), "passed": challenge.get("passed")},
    )
    origins = manifest.get("environment_origins", {})
    authentic = sum(int(value) for key, value in origins.items() if str(key).startswith("authentic_"))
    total = sum(map(int, manifest.get("counts", {}).values()))
    record(
        checks, "authentic_task_ratio_at_least_60_percent", total > 0 and authentic / total >= 0.60, authentic / total
    )
    v1_mismatches = {}
    for relative, expected in v1_lock["files"].items():
        path = project / relative
        actual = sha256(path) if path.is_file() else None
        if actual != expected:
            v1_mismatches[relative] = {"expected": expected, "actual": actual}
    record(checks, "benchmark_v1_frozen_integrity", not v1_mismatches, v1_mismatches)
    external_pin_errors = {}
    for name, row in registry["benchmarks"].items():
        locked = external_lock.get("benchmarks", {}).get(name, {})
        if locked.get("resolved_commit") != row["revision"]["resolved_commit"]:
            external_pin_errors[name] = locked.get("resolved_commit")
    record(checks, "external_registry_revisions_pinned", not external_pin_errors, external_pin_errors)
    record(checks, "external_adapter_smoke", external_smoke.get("status") == "PASS", external_smoke.get("benchmarks"))
    review_status = review.get("review_status", {})
    record(
        checks,
        "self_review_recorded_honestly",
        str(review_status.get("self_review", "")).startswith("COMPLETED_")
        and review_status.get("independent_human_review") == "NOT_RUN"
        and review_status.get("external_llm_judge") == "NOT_RUN",
        review_status,
    )
    manifest_hash_errors = []
    for relative, expected in manifest.get("public_files", {}).items():
        path = public_root / relative
        if not path.is_file() or sha256(path) != expected:
            manifest_hash_errors.append(f"public:{relative}")
    for relative, expected in manifest.get("hidden_files", {}).items():
        path = hidden_root / relative
        if not path.is_file() or sha256(path) != expected:
            manifest_hash_errors.append(f"hidden:{relative}")
    record(checks, "manifest_asset_hashes", not manifest_hash_errors, manifest_hash_errors)
    failures = [row for row in checks if not row["passed"]]
    status = "FROZEN_FOR_BASELINE" if not failures else "CANDIDATE_PENDING_QUALITY_AUDIT"
    builder_commit = resolve_commit(project, args.builder_commit or git_head(project))
    quality_without_time = {
        "schema_version": "studyhub.agentbench-quality-gate.v2",
        "benchmark_version": "studyhub-agentbench-v2",
        "benchmark_revision": "2.0.0",
        "builder_commit": builder_commit,
        "status": "PASS" if not failures else "FAIL",
        "summary": {"checks": len(checks), "passed": len(checks) - len(failures), "failed": len(failures)},
        "checks": checks,
    }
    quality_path = public_root / "quality-gate.json"
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    if quality_path.is_file():
        previous_quality = read_json(quality_path)
        previous_without_time = {key: value for key, value in previous_quality.items() if key != "generated_at"}
        if previous_without_time == quality_without_time:
            generated_at = str(previous_quality.get("generated_at", generated_at))
    quality_gate = {**quality_without_time, "generated_at": generated_at}
    quality_path.write_text(json.dumps(quality_gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    frozen_at = None
    if not failures:
        frozen_at = datetime.now(UTC).isoformat(timespec="seconds")
        if manifest.get("status") == status and manifest.get("builder_commit") == builder_commit:
            frozen_at = str(manifest.get("frozen_at") or frozen_at)
    manifest.update(
        {
            "benchmark_revision": "2.0.0",
            "status": status,
            "frozen_at": frozen_at,
            "builder_commit": builder_commit,
            "builder_source_sha256": sha256(project / "src/studyhub_agent/benchmark_v2/builder.py"),
            "review": review_status,
            "quality_artifacts": {
                "quality_gate": sha256(quality_path),
                "structural_audit_summary": sha256(public_root / "structural-audit-summary.json"),
                "semantic_audit_summary": sha256(public_root / "semantic-audit-summary.json"),
                "self_test_summary": sha256(public_root / "self-test-summary.json"),
                "evaluator_challenge_summary": sha256(public_root / "evaluator-challenge-summary.json"),
                "review_pack_manifest": sha256(public_root / "review-pack-manifest.json"),
                "self_review": sha256(project / "configs/benchmark-v2-self-review.json"),
                "external_portfolio_lock": sha256(external_lock_path),
                "external_smoke": sha256(external_smoke_path),
            },
            "external_portfolio": {
                name: {
                    "resolved_commit": row["resolved_commit"],
                    "setup_status": external_smoke["benchmarks"][name]["status"],
                }
                for name, row in external_lock["benchmarks"].items()
            },
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    hidden_manifest = {**manifest, "public_manifest_sha256": sha256(manifest_path)}
    (hidden_root / "manifest.json").write_text(
        json.dumps(hidden_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(quality_gate, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
