#!/usr/bin/env python3
"""Fail closed if legacy Teacher replay can enter the controlled SFT mainline."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def validate(project: Path) -> dict[str, Any]:
    paths = {
        "policy": project / "configs/program-v3/teacher-mainline-policy-v1.json",
        "program": project / "configs/program-v3/open-only-sft-v1.1-lrmatched.json",
        "authorization": project / "configs/program-v3/open-only-sft-v1.1-lrmatched-authorization.json",
        "data_card": project / "configs/program-v3/open-only-sft-v1-data-card.json",
        "legacy_consumption": project / "configs/program-v3/overnight-sft-baseline-consumption.json",
        "teacher_candidate": project / "docs/training/evidence/runtime-sft-v3.1-candidate-audit.json",
    }
    values = {name: load_json(path) for name, path in paths.items()}
    policy = values["policy"]
    program = values["program"]
    authorization = values["authorization"]
    data_card = values["data_card"]
    consumption = values["legacy_consumption"]
    candidate = values["teacher_candidate"]

    sources = set(data_card["selection"]["train_source_assistant_loss_shares"])
    forbidden = tuple(program["forbidden_source_prefixes"])
    teacher_sources = sorted(source for source in sources if source.startswith("studyhub_teacher_"))
    checks = {
        "policy_freezes_legacy_reverse_replay": policy["status"] == "LEGACY_REVERSE_REPLAY_FROZEN_NOT_MAINLINE",
        "active_program_forbids_teacher_prefix": "studyhub_teacher_" in forbidden,
        "active_dataset_has_no_teacher_source": not teacher_sources,
        "authorization_targets_open_only_dataset": authorization["scope"]["dataset"]
        == policy["active_sft_control"]["dataset_id"],
        "legacy_authorization_consumed_and_not_repeatable": consumption["status"] == "CONSUMED_COMPLETE"
        and consumption["scope"]["repeat_authorized"] is False,
        "teacher_candidate_not_formal": candidate["formal_release"] is False,
        "teacher_candidate_below_reentry_minimum": int(candidate["teacher_rows"])
        < int(policy["candidate_only"]["minimum_teacher_verified_rows"]),
        "sealed_unused": policy["scope"]["sealed_used"] is False and candidate["sealed_task_files_read"] is False,
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": "studyhub.teacher-mainline-policy-audit.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "PASS" if not failures else "FAIL",
        "decision": (
            "LEGACY_REVERSE_REPLAY_FROZEN_NOT_MAINLINE" if not failures else "BLOCKED_TEACHER_MAINLINE_POLICY_DRIFT"
        ),
        "checks": checks,
        "failures": failures,
        "observed": {
            "active_training_sources": sorted(sources),
            "teacher_sources_in_active_dataset": teacher_sources,
            "teacher_candidate_rows": candidate["teacher_rows"],
            "teacher_candidate_status": candidate["status"],
        },
        "inputs": {
            name: {"path": str(path.relative_to(project)), "sha256": sha256(path)} for name, path in paths.items()
        },
        "scope": {
            "rl_started": False,
            "sealed_used": False,
            "teacher_collection_started": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = validate(args.project_root.resolve())
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
