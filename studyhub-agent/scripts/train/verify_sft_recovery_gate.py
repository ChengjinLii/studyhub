#!/usr/bin/env python3
"""Verify that interrupted SFT matches an uninterrupted reference run."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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


def load_equivalence_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "studyhub.sft-recovery-equivalence-contract.v1":
        raise RuntimeError(f"unexpected equivalence contract: {path}")
    if payload.get("status") != "PRE_REGISTERED_BEFORE_CONFIRMATION_RUN":
        raise RuntimeError(f"equivalence contract is not pre-registered: {path}")
    return payload


def compare_adapters(
    reference: Path,
    recovered: Path,
    initial: Path,
    contract: dict[str, Any],
) -> dict[str, Any]:
    failures: list[str] = []
    tensor_rows: list[dict[str, Any]] = []
    thresholds = contract["adapter_thresholds"]
    with safe_open(reference, framework="pt", device="cpu") as left, safe_open(
        recovered, framework="pt", device="cpu"
    ) as right, safe_open(initial, framework="pt", device="cpu") as origin:
        left_keys = set(left.keys())
        right_keys = set(right.keys())
        origin_keys = set(origin.keys())
        missing = sorted(left_keys - right_keys)
        unexpected = sorted(right_keys - left_keys)
        initial_missing = sorted(left_keys - origin_keys)
        if missing:
            failures.append(f"missing_tensors:{len(missing)}")
        if unexpected:
            failures.append(f"unexpected_tensors:{len(unexpected)}")
        if initial_missing:
            failures.append(f"initial_missing_tensors:{len(initial_missing)}")

        exact_count = 0
        exact_elements = 0
        total_elements = 0
        max_absolute_difference = 0.0
        difference_l2_squared = 0.0
        reference_l2_squared = 0.0
        reference_update_l2_squared = 0.0
        recovered_update_l2_squared = 0.0
        update_dot_product = 0.0
        common_keys = left_keys & right_keys & origin_keys
        for key in sorted(common_keys):
            left_tensor = left.get_tensor(key)
            right_tensor = right.get_tensor(key)
            initial_tensor = origin.get_tensor(key)
            if left_tensor.shape != right_tensor.shape:
                failures.append(f"shape_mismatch:{key}")
                continue
            if left_tensor.dtype != right_tensor.dtype:
                failures.append(f"dtype_mismatch:{key}")
                continue
            if initial_tensor.shape != left_tensor.shape:
                failures.append(f"initial_shape_mismatch:{key}")
                continue
            exact = torch.equal(left_tensor, right_tensor)
            exact_count += int(exact)
            left_float = left_tensor.float()
            right_float = right_tensor.float()
            initial_float = initial_tensor.float()
            difference_tensor = left_float - right_float
            reference_update = left_float - initial_float
            recovered_update = right_float - initial_float
            difference = float(difference_tensor.abs().max()) if left_tensor.numel() else 0.0
            max_absolute_difference = max(max_absolute_difference, difference)
            exact_elements += int((left_tensor == right_tensor).sum())
            total_elements += left_tensor.numel()
            difference_l2_squared += float((difference_tensor * difference_tensor).sum())
            reference_l2_squared += float((left_float * left_float).sum())
            reference_update_l2_squared += float((reference_update * reference_update).sum())
            recovered_update_l2_squared += float((recovered_update * recovered_update).sum())
            update_dot_product += float((reference_update * recovered_update).sum())
            if not exact and len(tensor_rows) < 10:
                tensor_rows.append(
                    {
                        "name": key,
                        "shape": list(left_tensor.shape),
                        "dtype": str(left_tensor.dtype),
                        "max_absolute_difference": difference,
                    }
                )

    compared = len(common_keys)
    bitwise_equal = exact_count == compared and not missing and not unexpected
    difference_l2 = math.sqrt(difference_l2_squared)
    reference_l2 = math.sqrt(reference_l2_squared)
    reference_update_l2 = math.sqrt(reference_update_l2_squared)
    recovered_update_l2 = math.sqrt(recovered_update_l2_squared)
    relative_l2 = difference_l2 / max(reference_l2, 1e-30)
    relative_update_l2 = difference_l2 / max(reference_update_l2, 1e-30)
    update_cosine = update_dot_product / max(
        reference_update_l2 * recovered_update_l2,
        1e-30,
    )
    update_norm_ratio = recovered_update_l2 / max(reference_update_l2, 1e-30)

    if max_absolute_difference > float(thresholds["max_absolute_difference"]):
        failures.append("max_absolute_difference_exceeded")
    if relative_l2 > float(thresholds["max_relative_l2_to_reference"]):
        failures.append("relative_l2_to_reference_exceeded")
    if relative_update_l2 > float(
        thresholds["max_relative_l2_to_reference_update"]
    ):
        failures.append("relative_l2_to_reference_update_exceeded")
    if update_cosine < float(thresholds["min_update_cosine_similarity"]):
        failures.append("update_cosine_similarity_below_minimum")
    if not (
        float(thresholds["min_update_norm_ratio"])
        <= update_norm_ratio
        <= float(thresholds["max_update_norm_ratio"])
    ):
        failures.append("update_norm_ratio_out_of_bounds")
    return {
        "status": "PASS" if not failures else "FAIL",
        "equivalence_mode": "bitwise" if bitwise_equal else "bounded_numeric",
        "bitwise_equal": bitwise_equal,
        "contract_thresholds": thresholds,
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
        "element_count": total_elements,
        "exact_element_count": exact_elements,
        "exact_element_fraction": exact_elements / max(total_elements, 1),
        "file_sha256_equal": sha256(reference) == sha256(recovered),
        "max_absolute_difference": max_absolute_difference,
        "l2_difference": difference_l2,
        "relative_l2_to_reference": relative_l2,
        "relative_l2_to_reference_update": relative_update_l2,
        "reference_update_l2": reference_update_l2,
        "recovered_update_l2": recovered_update_l2,
        "update_cosine_similarity": update_cosine,
        "update_norm_ratio": update_norm_ratio,
        "first_tensor_differences": tensor_rows,
        "missing_tensors": missing,
        "unexpected_tensors": unexpected,
        "initial_missing_tensors": initial_missing,
        "failures": failures,
    }


def compare_continuation_metrics(
    continuous: Path,
    recovered: Path,
    *,
    start: int,
    count: int,
    contract: dict[str, Any],
) -> dict[str, Any]:
    left = json.loads(continuous.read_text(encoding="utf-8"))["series"]
    right = json.loads(recovered.read_text(encoding="utf-8"))["series"]
    thresholds = contract["continuation_thresholds"]
    failures: list[str] = []
    exact_series: dict[str, Any] = {}
    for key in thresholds["exact_series"]:
        reference_values = left.get(key, [])[start : start + count]
        recovered_values = right.get(key, [])[:count]
        equal = len(reference_values) == count and reference_values == recovered_values
        exact_series[key] = {
            "reference": reference_values,
            "recovered": recovered_values,
            "equal": equal,
        }
        if not equal:
            failures.append(f"continuation_series_mismatch:{key}")

    def paired_differences(key: str) -> tuple[list[float], list[float]]:
        reference_values = [float(value) for value in left.get(key, [])[start : start + count]]
        recovered_values = [float(value) for value in right.get(key, [])[:count]]
        if len(reference_values) != count or len(recovered_values) != count:
            failures.append(f"continuation_series_missing:{key}")
            return [math.nan] * count, [math.nan] * count
        if not all(math.isfinite(value) for value in reference_values + recovered_values):
            failures.append(f"continuation_non_finite:{key}")
        return reference_values, recovered_values

    loss_left, loss_right = paired_differences("sft/loss/avg")
    grad_left, grad_right = paired_differences("sft/grad_norm")
    entropy_left, entropy_right = paired_differences("sft/entropy/avg")
    first_loss_difference = abs(loss_left[0] - loss_right[0])
    max_loss_relative_difference = max(
        abs(a - b) / max(abs(a), 1e-12)
        for a, b in zip(loss_left, loss_right, strict=True)
    )
    max_grad_relative_difference = max(
        abs(a - b) / max(abs(a), 1e-12)
        for a, b in zip(grad_left, grad_right, strict=True)
    )
    max_entropy_absolute_difference = max(
        abs(a - b) for a, b in zip(entropy_left, entropy_right, strict=True)
    )
    if first_loss_difference > float(
        thresholds["max_first_step_loss_absolute_difference"]
    ):
        failures.append("first_recovered_loss_difference_exceeded")
    if max_loss_relative_difference > float(
        thresholds["max_tail_loss_relative_difference"]
    ):
        failures.append("tail_loss_relative_difference_exceeded")
    if max_grad_relative_difference > float(
        thresholds["max_tail_grad_norm_relative_difference"]
    ):
        failures.append("tail_grad_norm_relative_difference_exceeded")
    if max_entropy_absolute_difference > float(
        thresholds["max_tail_entropy_absolute_difference"]
    ):
        failures.append("tail_entropy_absolute_difference_exceeded")
    return {
        "status": "PASS" if not failures else "FAIL",
        "continuous_metrics": str(continuous.resolve()),
        "recovered_metrics": str(recovered.resolve()),
        "tail_start": start,
        "tail_count": count,
        "exact_series": exact_series,
        "diagnostics": {
            "first_step_loss_absolute_difference": first_loss_difference,
            "max_tail_loss_relative_difference": max_loss_relative_difference,
            "max_tail_grad_norm_relative_difference": max_grad_relative_difference,
            "max_tail_entropy_absolute_difference": max_entropy_absolute_difference,
        },
        "contract_thresholds": thresholds,
        "failures": failures,
    }


def load_shared_prefix_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if payload.get("schema_version") != "studyhub.sft-shared-prefix.v1":
        failures.append("unexpected_shared_prefix_schema")
    if payload.get("status") != "PASS":
        failures.append("shared_prefix_snapshot_failed")
    step_info = payload.get("step_info")
    if not isinstance(step_info, dict) or int(step_info.get("global_step", -1)) != 1:
        failures.append("shared_prefix_not_at_global_step_1")
    if payload.get("method") != "atomic_directory_rename_same_filesystem":
        failures.append("shared_prefix_not_atomically_branched")
    return {
        "status": "PASS" if not failures else "FAIL",
        "path": str(path.resolve()),
        "snapshot": payload,
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
    parser.add_argument("--initial-adapter", type=Path, required=True)
    parser.add_argument("--shared-prefix-report", type=Path, required=True)
    parser.add_argument("--equivalence-contract", type=Path, required=True)
    parser.add_argument("--continuous-tail-metrics", type=Path, required=True)
    parser.add_argument("--recovered-tail-metrics", type=Path, required=True)
    parser.add_argument("--tail-start", type=int, required=True)
    parser.add_argument("--tail-count", type=int, required=True)
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
    contract = load_equivalence_contract(args.equivalence_contract)
    shared_prefix = load_shared_prefix_report(args.shared_prefix_report)
    continuation = compare_continuation_metrics(
        args.continuous_tail_metrics,
        args.recovered_tail_metrics,
        start=args.tail_start,
        count=args.tail_count,
        contract=contract,
    )
    adapter = compare_adapters(
        args.continuous_adapter,
        args.recovered_adapter,
        args.initial_adapter,
        contract,
    )
    failures = []
    if continuous_lr["status"] != "PASS":
        failures.append("continuous_lr_contract_failed")
    if recovered_lr["status"] != "PASS":
        failures.append("recovered_lr_contract_failed")
    if shared_prefix["status"] != "PASS":
        failures.append("shared_prefix_contract_failed")
    if continuation["status"] != "PASS":
        failures.append("continuation_metrics_contract_failed")
    if adapter["status"] != "PASS":
        failures.append("recovered_adapter_differs_from_continuous")

    result = {
        "schema_version": "studyhub.sft-recovery-gate.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "PASS" if not failures else "FAIL",
        "claim": (
            "Under one tested recovery boundary, the pinned AReaL SFT stack produced "
            "the authorized LR trajectory, exact continuation sample-shape signature, "
            "and pre-registered bounded numerical LoRA equivalence with the uninterrupted "
            "reference. Bitwise identity is reported separately."
            if not failures
            else "The tested interrupted SFT path is not equivalent to the uninterrupted reference."
        ),
        "scope": {
            "model_quality": "NOT_EVALUATED",
            "rl_started": False,
            "sealed_used": False,
            "expected_updates_per_path": args.expected_updates,
        },
        "equivalence_contract": {
            "path": str(args.equivalence_contract.resolve()),
            "sha256": sha256(args.equivalence_contract),
            "payload": contract,
        },
        "continuous_lr": continuous_lr,
        "recovered_lr": recovered_lr,
        "shared_prefix": shared_prefix,
        "continuation_metrics": continuation,
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
