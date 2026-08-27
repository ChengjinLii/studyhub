#!/usr/bin/env python3
"""Fail-closed validation for external registry and lock metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from external_benchmarks.registry import load_registry  # noqa: E402 - standalone script bootstraps project root

LOCK_SCHEMA = "studyhub.external-benchmark-lock.v1"
_SECRET_VALUE = re.compile(r"(?i)(?:sk-|tp-|hf_)[a-z0-9_-]{12,}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_lock(registry_path: Path, lock_path: Path) -> dict[str, Any]:
    registry = load_registry(registry_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if lock.get("schema_version") != LOCK_SCHEMA:
        failures.append("lock schema mismatch")
    if lock.get("portfolio_version") != registry.get("portfolio_version"):
        failures.append("portfolio version mismatch")
    if lock.get("registry_sha256") != sha256(registry_path):
        failures.append("registry hash mismatch")
    rows = lock.get("benchmarks")
    if not isinstance(rows, dict) or set(rows) != set(registry["benchmarks"]):
        failures.append("lock benchmark set mismatch")
        rows = rows if isinstance(rows, dict) else {}
    for name, expected in registry["benchmarks"].items():
        row = rows.get(name, {})
        if row.get("upstream") != expected["upstream"]:
            failures.append(f"{name}: upstream mismatch")
        if row.get("resolved_commit") != expected["revision"]["resolved_commit"]:
            failures.append(f"{name}: commit mismatch")
        if row.get("license") != expected["license"]:
            failures.append(f"{name}: license mismatch")
        if set(row.get("artifact_hashes", {})) != set(expected["expected_paths"]):
            failures.append(f"{name}: artifact hash coverage mismatch")
        expected_status = "LICENSE_REVIEW_REQUIRED" if expected["license"]["status"] == "unconfirmed" else "FETCHED"
        if row.get("setup_status") != expected_status:
            failures.append(f"{name}: setup status is not {expected_status}")
        if bool(row.get("source_exported")) != bool(expected.get("export_allowed")):
            failures.append(f"{name}: source export policy mismatch")
        if row.get("data_assets", []) != expected.get("data_assets", []):
            failures.append(f"{name}: data asset pins mismatch")
    serialized = json.dumps({"registry": registry, "lock": lock}, ensure_ascii=False)
    if _SECRET_VALUE.search(serialized):
        failures.append("registry or lock contains a secret-like literal")
    return {
        "schema_version": "studyhub.external-registry-validation.v1",
        "status": "PASS" if not failures else "FAIL",
        "checks": {
            "benchmarks": len(registry["benchmarks"]),
            "all_revisions_pinned": all(
                re.fullmatch(r"[0-9a-f]{40}", row["revision"]["resolved_commit"])
                for row in registry["benchmarks"].values()
            ),
            "license_review_required": sorted(
                name for name, row in registry["benchmarks"].items() if row["license"]["status"] == "unconfirmed"
            ),
            "failures": failures,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=PROJECT_ROOT / "external_benchmarks/registry.yaml")
    parser.add_argument("--lock", type=Path, default=PROJECT_ROOT / "external_benchmarks/lock.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_lock(args.registry, args.lock)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
