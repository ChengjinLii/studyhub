#!/usr/bin/env python3
"""Validate the frozen public manifest and its ignored local sealed counterpart."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=project)
    parser.add_argument("--public-root", type=Path, default=project / "benchmarks/studyhub-agent-v2")
    parser.add_argument("--hidden-root", type=Path, default=project / "artifacts/benchmark-v2/studyhub-agent-v2")
    parser.add_argument("--require-frozen", action="store_true")
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help=("Validate ignored hidden assets. Requires STUDYHUB_ALLOW_SEALED_VALIDATION=YES."),
    )
    return parser.parse_args()


def validate(args: argparse.Namespace) -> dict[str, Any]:
    project = args.project.resolve()
    public = args.public_root.resolve()
    hidden = args.hidden_root.resolve()
    manifest_path = public / "manifest.json"
    manifest = read_json(manifest_path)
    failures: list[str] = []
    include_hidden = bool(args.include_hidden)

    if include_hidden and os.environ.get("STUDYHUB_ALLOW_SEALED_VALIDATION") != "YES":
        return {
            "schema_version": "studyhub.agentbench-manifest-validation.v2",
            "status": "FAIL",
            "benchmark_status": manifest.get("status"),
            "public_assets": 0,
            "hidden_assets_checked": 0,
            "quality_artifacts": 0,
            "failures": ["hidden validation requires STUDYHUB_ALLOW_SEALED_VALIDATION=YES"],
        }

    if args.require_frozen and manifest.get("status") != "FROZEN_FOR_BASELINE":
        failures.append(f"benchmark status is {manifest.get('status')!r}, not FROZEN_FOR_BASELINE")

    for relative, expected in manifest.get("public_files", {}).items():
        path = public / relative
        if not path.is_file():
            failures.append(f"missing public asset: {relative}")
        elif sha256(path) != expected:
            failures.append(f"public asset hash mismatch: {relative}")

    if include_hidden:
        for relative, expected in manifest.get("hidden_files", {}).items():
            path = hidden / relative
            if not path.is_file():
                failures.append(f"missing hidden asset: {relative}")
            elif sha256(path) != expected:
                failures.append(f"hidden asset hash mismatch: {relative}")

    quality_paths = {
        "quality_gate": public / "quality-gate.json",
        "structural_audit_summary": public / "structural-audit-summary.json",
        "semantic_audit_summary": public / "semantic-audit-summary.json",
        "self_test_summary": public / "self-test-summary.json",
        "evaluator_challenge_summary": public / "evaluator-challenge-summary.json",
        "review_pack_manifest": public / "review-pack-manifest.json",
        "self_review": project / "configs/benchmark-v2-self-review.json",
        "external_portfolio_lock": project / "external_benchmarks/lock.json",
        "external_smoke": project / "external_benchmarks/smoke-status.json",
    }
    for name, expected in manifest.get("quality_artifacts", {}).items():
        path = quality_paths.get(name)
        if path is None:
            failures.append(f"unknown quality artifact: {name}")
        elif not path.is_file():
            failures.append(f"missing quality artifact: {name}")
        elif sha256(path) != expected:
            failures.append(f"quality artifact hash mismatch: {name}")

    builder_commit = manifest.get("builder_commit")
    if builder_commit:
        resolved = subprocess.run(
            ["git", "cat-file", "-e", f"{builder_commit}^{{commit}}"],
            cwd=project,
            capture_output=True,
        )
        if resolved.returncode:
            failures.append(f"builder commit is unavailable: {builder_commit}")
    builder = project / "src/studyhub_agent/benchmark_v2/builder.py"
    expected_builder_hash = manifest.get("builder_source_sha256")
    if expected_builder_hash and sha256(builder) != expected_builder_hash:
        failures.append("builder source hash mismatch")

    quality_path = public / "quality-gate.json"
    if quality_path.is_file() and builder_commit:
        quality = read_json(quality_path)
        if quality.get("builder_commit") != builder_commit:
            failures.append("quality gate builder commit does not match manifest")
        if args.require_frozen and quality.get("status") != "PASS":
            failures.append("frozen manifest points to a failing quality gate")

    if include_hidden:
        hidden_manifest_path = hidden / "manifest.json"
        if not hidden_manifest_path.is_file():
            failures.append("missing hidden manifest")
        else:
            hidden_manifest = read_json(hidden_manifest_path)
            if hidden_manifest.get("public_manifest_sha256") != sha256(manifest_path):
                failures.append("hidden manifest does not bind the current public manifest")

    return {
        "schema_version": "studyhub.agentbench-manifest-validation.v2",
        "status": "PASS" if not failures else "FAIL",
        "benchmark_status": manifest.get("status"),
        "public_assets": len(manifest.get("public_files", {})),
        "hidden_assets_checked": (len(manifest.get("hidden_files", {})) if include_hidden else 0),
        "quality_artifacts": len(manifest.get("quality_artifacts", {})),
        "failures": failures,
    }


def main() -> int:
    report = validate(parse_args())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
