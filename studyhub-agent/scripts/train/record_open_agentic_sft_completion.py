#!/usr/bin/env python3
"""Record a fail-closed Open-Agentic SFT smoke or formal completion marker."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.train.record_formal_sft_completion import build_marker, load_json, sha256
from scripts.train.record_open_only_sft_completion import validate_lr_audit


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
        raise RuntimeError("Open-Agentic authorization is not pending")
    budget_key = "smoke_optimizer_updates" if args.mode == "smoke" else "planned_optimizer_updates"
    if args.expected_updates != int(authorization["budget"][budget_key]):
        raise RuntimeError("completion update count differs from authorization")

    marker = build_marker(args)
    metadata = load_json(args.run_metadata)
    if metadata.get("run_authorization", {}).get("sha256") != sha256(args.authorization):
        raise RuntimeError("run metadata is not bound to the Open-Agentic authorization")
    lr_audit = load_json(args.lr_audit)
    validate_lr_audit(lr_audit, authorization, expected_updates=args.expected_updates)

    initial = args.checkpoint_root / "actor/initial_lora/adapter_model.safetensors"
    if not initial.is_file():
        raise RuntimeError("initial LoRA checkpoint is missing")
    initial_hash = sha256(initial)
    if initial_hash == marker["checkpoint"]["sha256"]:
        raise RuntimeError("LoRA parameters did not update")

    recovery_inventory = None
    if args.mode == "smoke":
        metadata_files = list(args.checkpoint_root.rglob("recover_checkpoint/.metadata"))
        state_files = list(args.checkpoint_root.rglob("recover_checkpoint/*.distcp"))
        if len(metadata_files) != 1 or not state_files:
            raise RuntimeError("smoke did not produce a complete recovery checkpoint")
        recovery_inventory = {
            "metadata": str(metadata_files[0].resolve()),
            "state_files": len(state_files),
            "state_bytes": sum(path.stat().st_size for path in state_files),
        }

    marker.update(
        {
            "schema_version": "studyhub.open-agentic-sft-completion.v2",
            "status": "SMOKE_PASS" if args.mode == "smoke" else "COMPLETE",
            "mode": args.mode,
            "authorization_id": authorization["authorization_id"],
            "authorization_sha256": sha256(args.authorization),
            "dataset_manifest_sha256": authorization["lineage"]["dataset_manifest_sha256"],
            "initial_lora_sha256": initial_hash,
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
                "NOT_EVALUATED_SMOKE_ONLY" if args.mode == "smoke" else "PENDING_INDEPENDENT_DEVELOPMENT_EVALUATION"
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
