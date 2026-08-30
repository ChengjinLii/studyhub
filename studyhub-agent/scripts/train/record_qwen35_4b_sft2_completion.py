#!/usr/bin/env python3
"""Record SFT-2 only when M1 initialization and optimizer updates are proven."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import torch
from safetensors.torch import load_file

from scripts.train.record_formal_sft_completion import (
    build_marker,
    final_adapter,
    load_json,
    override_value,
    sha256,
)
from scripts.train.record_open_only_sft_completion import validate_lr_audit


def exact_adapter_match(left: Path, right: Path) -> dict[str, Any]:
    left_state = load_file(str(left), device="cpu")
    right_state = load_file(str(right), device="cpu")
    keys_match = set(left_state) == set(right_state)
    mismatches = []
    if keys_match:
        for key in sorted(left_state):
            if not torch.equal(left_state[key], right_state[key]):
                mismatches.append(key)
                if len(mismatches) >= 8:
                    break
    return {
        "status": "PASS" if keys_match and not mismatches else "FAIL",
        "keys_match": keys_match,
        "tensor_count": len(left_state),
        "first_mismatched_keys": mismatches,
        "left_sha256": sha256(left),
        "right_sha256": sha256(right),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "formal"), required=True)
    parser.add_argument("--run-metadata", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--lr-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-updates", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    authorization = load_json(args.authorization)
    if authorization.get("status") != "AUTHORIZED_PENDING_SMOKE_AND_FORMAL_RUN":
        raise RuntimeError("SFT-2 authorization is not pending")
    budget_key = (
        "smoke_optimizer_updates"
        if args.mode == "smoke"
        else "planned_optimizer_updates"
    )
    if args.expected_updates != int(authorization["budget"][budget_key]):
        raise RuntimeError("completion update count differs from authorization")
    metadata = load_json(args.run_metadata)
    if metadata.get("run_authorization", {}).get("sha256") != sha256(
        args.authorization
    ):
        raise RuntimeError("run metadata is not bound to the SFT-2 authorization")
    lr_audit = load_json(args.lr_audit)
    validate_lr_audit(lr_audit, authorization, expected_updates=args.expected_updates)

    initial = args.checkpoint_root / "actor/initial_lora/adapter_model.safetensors"
    m1 = Path(authorization["lineage"]["m1_adapter_path"]) / "adapter_model.safetensors"
    if not initial.is_file() or not m1.is_file():
        raise RuntimeError("SFT-2 initial or M1 LoRA adapter is missing")
    initialization = exact_adapter_match(initial, m1)
    if initialization["status"] != "PASS":
        raise RuntimeError(
            f"SFT-2 did not initialize exactly from M1: {initialization}"
        )

    if args.mode == "formal":
        marker = build_marker(args)
    else:
        if metadata.get("exit_status") != 0:
            raise RuntimeError("SFT-2 smoke attempt did not exit successfully")
        trial = override_value(metadata, "trial_name")
        checkpoint_step, adapter = final_adapter(args.checkpoint_root)
        cadence = int(authorization["budget"]["smoke_checkpoint_every_updates"])
        if checkpoint_step + 1 < cadence or checkpoint_step >= args.expected_updates:
            raise RuntimeError("SFT-2 smoke checkpoint cadence is invalid")
        coverage = lr_audit.get("coverage", {})
        if coverage.get("last_global_step") != args.expected_updates - 1:
            raise RuntimeError("SFT-2 smoke LR evidence is incomplete")
        benchmark = metadata.get("benchmark", {})
        if (
            benchmark.get("status") != "FROZEN_FOR_BASELINE"
            or benchmark.get("sealed_content_used") is not False
        ):
            raise RuntimeError("SFT-2 smoke is not bound to public Benchmark v2")
        marker = {
            "schema_version": "studyhub.qwen35-4b-sft2-completion.v1",
            "status": "SMOKE_PASS",
            "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "training_trial": trial,
            "completed_attempt": args.run_metadata.stem.removesuffix(".run"),
            "expected_optimizer_updates": args.expected_updates,
            "final_global_step": coverage["last_global_step"],
            "last_saved_adapter_global_step": checkpoint_step,
            "checkpoint": {
                "path": str(adapter.resolve()),
                "bytes": adapter.stat().st_size,
                "sha256": sha256(adapter),
            },
            "dataset_manifest_sha256": metadata.get("dataset_manifest_sha256"),
            "benchmark_manifest_sha256": benchmark.get("sha256"),
            "git_commit": metadata.get("git", {}).get("commit"),
        }

    final_weights = Path(marker["checkpoint"]["path"])
    if sha256(final_weights) == sha256(initial):
        raise RuntimeError("SFT-2 LoRA parameters did not update")
    recovery_inventory = None
    if args.mode == "smoke":
        metadata_files = list(
            args.checkpoint_root.rglob("recover_checkpoint/.metadata")
        )
        state_files = list(args.checkpoint_root.rglob("recover_checkpoint/*.distcp"))
        if len(metadata_files) != 1 or not state_files:
            raise RuntimeError("SFT-2 smoke has no complete recovery checkpoint")
        recovery_inventory = {
            "metadata": str(metadata_files[0].resolve()),
            "state_files": len(state_files),
            "state_bytes": sum(path.stat().st_size for path in state_files),
        }
    marker.update(
        {
            "schema_version": "studyhub.qwen35-4b-sft2-completion.v1",
            "status": "SMOKE_PASS" if args.mode == "smoke" else "COMPLETE",
            "mode": args.mode,
            "authorization_id": authorization["authorization_id"],
            "authorization_sha256": sha256(args.authorization),
            "teacher_interface": "codex-cli",
            "teacher_model": "gpt-5.6-sol",
            "m1_initialization_verified": True,
            "m1_initialization": initialization,
            "lora_update_observed": True,
            "lr_schedule_audit": {
                "path": str(args.lr_audit.resolve()),
                "sha256": sha256(args.lr_audit),
                "status": lr_audit["status"],
                "coverage": lr_audit["coverage"],
            },
            "recovery_checkpoint": recovery_inventory,
            "sealed_used": False,
            "rl_started": False,
            "quality_claim": (
                "NOT_EVALUATED_SMOKE_ONLY"
                if args.mode == "smoke"
                else "PENDING_INDEPENDENT_EVALUATION"
            ),
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, args.output)
    print(json.dumps(marker, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
