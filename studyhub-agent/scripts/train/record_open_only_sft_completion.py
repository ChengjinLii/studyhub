#!/usr/bin/env python3
"""Write a fail-closed completion marker for the Open-Only SFT control."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.train.record_formal_sft_completion import build_marker, load_json, sha256


def validate_lr_audit(
    audit: dict,
    authorization: dict,
    *,
    expected_updates: int,
) -> None:
    if audit.get("status") != "PASS":
        raise RuntimeError(f"LR schedule audit failed: {audit.get('failures')}")
    contract = audit.get("contract", {})
    recipe = authorization.get("recipe", {})
    completion = authorization.get("completion_contract", {})
    expected = {
        "scheduler": recipe.get("scheduler"),
        "scheduler_total_steps": completion.get("expected_scheduler_total_steps"),
        "base_lr": recipe.get("learning_rate"),
        "warmup_fraction": recipe.get("warmup_fraction"),
        "warmup_steps": completion.get("expected_warmup_steps"),
        "expected_updates": expected_updates,
        "expected_start_step": 0,
    }
    mismatches = {
        key: {"expected": value, "actual": contract.get(key)}
        for key, value in expected.items()
        if contract.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"LR audit contract differs from authorization: {mismatches}")
    coverage = audit.get("coverage", {})
    if (
        int(coverage.get("observed_updates", -1)) != expected_updates
        or int(coverage.get("first_global_step", -1)) != 0
        or int(coverage.get("last_global_step", -1)) != expected_updates - 1
        or int(audit.get("mismatch_count", -1)) != 0
    ):
        raise RuntimeError("LR audit does not prove exact update coverage")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-metadata", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-updates", type=int, required=True)
    parser.add_argument("--lr-audit", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    authorization = load_json(args.authorization)
    budget = authorization.get("budget", {})
    if authorization.get("status") != "AUTHORIZED_PENDING_RUN":
        raise RuntimeError("Open-Only authorization is not pending")
    if args.expected_updates != budget.get("planned_optimizer_updates"):
        raise RuntimeError("completion update count differs from authorization")
    marker = build_marker(args)
    metadata = load_json(args.run_metadata)
    captured = metadata.get("run_authorization", {})
    if captured.get("sha256") != sha256(args.authorization):
        raise RuntimeError("run metadata is not bound to this authorization")
    lr_audit = None
    if authorization.get("completion_contract", {}).get(
        "require_lr_schedule_audit"
    ):
        if args.lr_audit is None or not args.lr_audit.is_file():
            raise RuntimeError("completion requires an LR schedule audit")
        lr_audit = load_json(args.lr_audit)
        validate_lr_audit(
            lr_audit,
            authorization,
            expected_updates=args.expected_updates,
        )
    marker.update(
        {
            "schema_version": (
                "studyhub.open-only-sft-completion.v1.1"
                if lr_audit is not None
                else "studyhub.open-only-sft-completion.v1"
            ),
            "authorization_id": authorization["authorization_id"],
            "authorization_sha256": sha256(args.authorization),
            "maximum_wall_time_seconds": budget["maximum_wall_time_seconds"],
            "controlled_variable": "training_data",
            "no_rl": authorization["scope"]["no_rl"],
            "sealed_used": False,
            "quality_claim": "PENDING_INDEPENDENT_DEVELOPMENT_EVALUATION",
            "lr_schedule_audit": (
                {
                    "path": str(args.lr_audit.resolve()),
                    "sha256": sha256(args.lr_audit),
                    "status": lr_audit["status"],
                    "contract": lr_audit["contract"],
                }
                if lr_audit is not None
                else None
            ),
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps(marker, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
