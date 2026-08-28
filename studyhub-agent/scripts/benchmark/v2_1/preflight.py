#!/usr/bin/env python3
"""Validate the v2.1 design without reading or creating Sealed content."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def validate_design(project: Path) -> dict[str, Any]:
    plan_path = project / "benchmarks/studyhub-agent-v2.1-design/plan.json"
    v2_manifest_path = project / "benchmarks/studyhub-agent-v2/manifest.json"
    plan = load_json(plan_path)
    v2_manifest = load_json(v2_manifest_path)
    capability_rows = plan["development_capability_plan"]
    checks = {
        "independent_successor": plan["relationship_to_v2"] == "INDEPENDENT_SUCCESSOR_DO_NOT_MUTATE_V2",
        "development_target_in_range": 300 <= plan["targets"]["development"] <= 500,
        "sealed_a_target_in_range": 100 <= plan["targets"]["sealed_a"] <= 150,
        "sealed_b_target_in_range": 100 <= plan["targets"]["sealed_b"] <= 150,
        "capability_counts_match_development_target": sum(int(row["tasks"]) for row in capability_rows)
        == int(plan["targets"]["development"]),
        "all_capabilities_have_multiple_source_groups": all(
            int(row["minimum_source_groups"]) >= 12 for row in capability_rows
        ),
        "public_builder_excludes_sealed": set(plan["generation_contract"]["public_splits_allowed"])
        == {"development", "calibration"},
        "sealed_generation_not_run": plan["generation_contract"]["sealed_generation_current_status"] == "NOT_RUN",
        "independent_semantic_review_required": plan["quality_contract"]["independent_semantic_review_for_open_tasks"]
        is True,
        "frozen_v2_status_unchanged": v2_manifest["status"] == "FROZEN_FOR_BASELINE",
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": "studyhub.agentbench-v2.1-design-preflight.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "PASS" if not failures else "FAIL",
        "design_status": plan["status"],
        "checks": checks,
        "failures": failures,
        "pipeline_stages": {
            "design_and_public_builder": "READY",
            "independent_source_acquisition": "NOT_RUN",
            "public_candidate_generation": "NOT_RUN",
            "independent_semantic_review": "NOT_RUN",
            "challenge_and_shortcut_tests": "NOT_RUN",
            "benchmark_freeze": "NOT_RUN",
            "sealed_generation": "NOT_RUN_PROHIBITED_BEFORE_FINAL_FREEZE",
            "model_evaluation": "NOT_RUN",
        },
        "scope": {
            "sealed_accessed": False,
            "v2_modified": False,
            "model_claim_allowed": False,
        },
        "inputs": {
            "plan": {
                "path": str(plan_path.relative_to(project)),
                "sha256": sha256(plan_path),
            },
            "frozen_v2_manifest": {
                "path": str(v2_manifest_path.relative_to(project)),
                "sha256": sha256(v2_manifest_path),
            },
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = validate_design(args.project_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(json.dumps({"status": payload["status"], "output": str(args.output)}))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
