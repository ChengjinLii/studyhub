#!/usr/bin/env python3
"""Verify that interrupted SFT matches an uninterrupted reference run."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import torch
from safetensors import safe_open

from scripts.train.audit_sft_lr_schedule import audit, parse_segment


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compare_adapters(reference: Path, recovered: Path) -> dict[str, Any]:
    failures: list[str] = []
    tensor_rows: list[dict[str, Any]] = []
    with safe_open(reference, framework="pt", device="cpu") as left, safe_open(
        recovered, framework="pt", device="cpu"
    ) as right:
        left_keys = set(left.keys())
        right_keys = set(right.keys())
        missing = sorted(left_keys - right_keys)
        unexpected = sorted(right_keys - left_keys)
        if missing:
            failures.append(f"missing_tensors:{len(missing)}")
        if unexpected:
            failures.append(f"unexpected_tensors:{len(unexpected)}")

        exact_count = 0
        max_absolute_difference = 0.0
        for key in sorted(left_keys & right_keys):
            left_tensor = left.get_tensor(key)
            right_tensor = right.get_tensor(key)
            if left_tensor.shape != right_tensor.shape:
                failures.append(f"shape_mismatch:{key}")
                continue
            if left_tensor.dtype != right_tensor.dtype:
                failures.append(f"dtype_mismatch:{key}")
                continue
            exact = torch.equal(left_tensor, right_tensor)
            exact_count += int(exact)
            difference = (
                float((left_tensor.float() - right_tensor.float()).abs().max())
                if left_tensor.numel()
                else 0.0
            )
            max_absolute_difference = max(max_absolute_difference, difference)
            if not exact and len(tensor_rows) < 10:
                tensor_rows.append(
                    {
                        "name": key,
                        "shape": list(left_tensor.shape),
                        "dtype": str(left_tensor.dtype),
                        "max_absolute_difference": difference,
                    }
                )

    compared = len(left_keys & right_keys)
    if exact_count != compared:
        failures.append(f"nonidentical_tensors:{compared - exact_count}")
    return {
        "status": "PASS" if not failures else "FAIL",
        "reference": {
            "path": str(reference.resolve()),
            "sha256": sha256(reference),
        },
        "recovered": {
            "path": str(recovered.resolve()),
            "sha256": sha256(recovered),
        },
        "tensor_key_count": compared,
        "exact_tensor_count": exact_count,
        "file_sha256_equal": sha256(reference) == sha256(recovered),
        "max_absolute_difference": max_absolute_difference,
        "first_tensor_differences": tensor_rows,
        "missing_tensors": missing,
        "unexpected_tensors": unexpected,
        "failures": failures,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--continuous-segment",
        action="append",
        type=parse_segment,
        required=True,
    )
    parser.add_argument(
        "--recovered-segment",
        action="append",
        type=parse_segment,
        required=True,
    )
    parser.add_argument("--continuous-adapter", type=Path, required=True)
    parser.add_argument("--recovered-adapter", type=Path, required=True)
    parser.add_argument("--base-lr", type=float, required=True)
    parser.add_argument("--scheduler-total-steps", type=int, required=True)
    parser.add_argument("--warmup-fraction", type=float, required=True)
    parser.add_argument("--expected-updates", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    continuous_lr = audit(
        args.continuous_segment,
        base_lr=args.base_lr,
        total_steps=args.scheduler_total_steps,
        warmup_fraction=args.warmup_fraction,
        expected_updates=args.expected_updates,
    )
    recovered_lr = audit(
        args.recovered_segment,
        base_lr=args.base_lr,
        total_steps=args.scheduler_total_steps,
        warmup_fraction=args.warmup_fraction,
        expected_updates=args.expected_updates,
    )
    adapter = compare_adapters(args.continuous_adapter, args.recovered_adapter)
    failures = []
    if continuous_lr["status"] != "PASS":
        failures.append("continuous_lr_contract_failed")
    if recovered_lr["status"] != "PASS":
        failures.append("recovered_lr_contract_failed")
    if adapter["status"] != "PASS":
        failures.append("recovered_adapter_differs_from_continuous")

    result = {
        "schema_version": "studyhub.sft-recovery-gate.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "PASS" if not failures else "FAIL",
        "claim": (
            "Under one tested recovery boundary, the pinned AReaL SFT stack produced "
            "the authorized LR trajectory and an exact final LoRA tensor match with "
            "the uninterrupted reference."
            if not failures
            else "The tested interrupted SFT path is not equivalent to the uninterrupted reference."
        ),
        "scope": {
            "model_quality": "NOT_EVALUATED",
            "rl_started": False,
            "sealed_used": False,
            "expected_updates_per_path": args.expected_updates,
        },
        "continuous_lr": continuous_lr,
        "recovered_lr": recovered_lr,
        "adapter_comparison": adapter,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
