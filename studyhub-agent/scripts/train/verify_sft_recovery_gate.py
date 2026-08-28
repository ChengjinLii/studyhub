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
    if payload.get("status") not in {
        "PRE_REGISTERED_BEFORE_CONFIRMATION_RUN",
        "CALIBRATED_ON_DISCLOSED_RUNS_AND_FROZEN_BEFORE_HOLDOUT_CONFIRMATION",
    }:
        raise RuntimeError(f"equivalence contract has an invalid lifecycle state: {path}")
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


def _load_audit_lane(root: Path, lane: str) -> dict[int, list[dict[str, Any]]]:
    directory = root / lane
    if not directory.is_dir():
        raise RuntimeError(f"missing recovery audit lane: {directory}")
    by_rank: dict[int, list[dict[str, Any]]] = {}
    for path in sorted(directory.glob("rank-*.jsonl")):
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not rows:
            raise RuntimeError(f"empty recovery audit file: {path}")
        rank = int(rows[0]["rank"])
        if any(int(row["rank"]) != rank for row in rows):
            raise RuntimeError(f"mixed ranks in recovery audit file: {path}")
        if rank in by_rank:
            raise RuntimeError(f"duplicate recovery audit rank: {rank}")
        by_rank[rank] = rows
    if not by_rank:
        raise RuntimeError(f"no recovery audit rows found: {directory}")
    return by_rank


def compare_batch_fingerprints(
    continuous_root: Path,
    recovered_root: Path,
    *,
    start: int,
    count: int,
) -> dict[str, Any]:
    left = _load_audit_lane(continuous_root, "batches")
    right = _load_audit_lane(recovered_root, "batches")
    failures: list[str] = []
    if set(left) != set(right):
        failures.append("batch_audit_rank_set_mismatch")
    declared_world_sizes = {
        int(row.get("world_size", -1))
        for rows in [*left.values(), *right.values()]
        for row in rows
    }
    if len(declared_world_sizes) != 1 or set(left) != set(
        range(next(iter(declared_world_sizes), -1))
    ):
        failures.append("batch_audit_world_size_mismatch")
    expected_steps = list(range(start, start + count))
    comparisons = []
    keys = (
        "batch_sha256",
        "sample_sha256",
        "input_ids_sha256",
        "loss_mask_sha256",
    )
    for rank in sorted(set(left) & set(right)):
        left_steps = {int(row["global_step"]): row for row in left[rank]}
        right_steps = {int(row["global_step"]): row for row in right[rank]}
        if len(left_steps) != len(left[rank]) or len(right_steps) != len(right[rank]):
            failures.append(f"duplicate_batch_step:rank_{rank}")
        for step in expected_steps:
            reference = left_steps.get(step)
            resumed = right_steps.get(step)
            if reference is None or resumed is None:
                failures.append(f"missing_batch_fingerprint:rank_{rank}:step_{step}")
                continue
            equal = all(reference.get(key) == resumed.get(key) for key in keys)
            comparisons.append(
                {
                    "rank": rank,
                    "global_step": step,
                    "equal": equal,
                    "reference_batch_sha256": reference.get("batch_sha256"),
                    "recovered_batch_sha256": resumed.get("batch_sha256"),
                    "sample_count": reference.get("sample_count"),
                }
            )
            if not equal:
                failures.append(f"batch_fingerprint_mismatch:rank_{rank}:step_{step}")
    return {
        "status": "PASS" if not failures else "FAIL",
        "continuous_audit_root": str(continuous_root.resolve()),
        "recovered_audit_root": str(recovered_root.resolve()),
        "expected_steps": expected_steps,
        "ranks": sorted(set(left) & set(right)),
        "declared_world_sizes": sorted(declared_world_sizes),
        "comparisons": comparisons,
        "failures": failures,
    }


def verify_state_continuity(
    shared_prefix: dict[str, Any],
    continuous_root: Path,
    recovered_root: Path,
    *,
    expected_prefix_global_step: int,
) -> dict[str, Any]:
    continuous = _load_audit_lane(continuous_root, "state")
    recovered = _load_audit_lane(recovered_root, "state")
    failures: list[str] = []
    inventory = {
        row["path"]: row
        for row in shared_prefix.get("snapshot", {})
        .get("target_inventory", {})
        .get("files", [])
    }
    rank_set = set(continuous) & set(recovered)
    if set(continuous) != set(recovered):
        failures.append("state_audit_rank_set_mismatch")
    snapshot_world_size = int(
        shared_prefix.get("snapshot", {}).get("runtime", {}).get("world_size", -1)
    )
    if rank_set != set(range(snapshot_world_size)):
        failures.append("state_audit_world_size_mismatch")
    rows = []
    for rank in sorted(rank_set):
        saved = [
            row
            for row in continuous[rank]
            if row.get("event") == "state_saved"
            and int(row.get("global_step", -1)) == expected_prefix_global_step
        ]
        restored = [row for row in recovered[rank] if row.get("event") == "state_restored"]
        if len(saved) != 1:
            failures.append(f"expected_one_saved_state:rank_{rank}")
            continue
        if len(restored) != 1:
            failures.append(f"expected_one_restored_state:rank_{rank}")
            continue
        saved_row = saved[0]
        restored_row = restored[0]
        rng_path = f"recover_info/rng_state_rank_{rank}.pt"
        snapshot_rng = inventory.get(rng_path, {}).get("sha256")
        rng_equal = (
            snapshot_rng
            and snapshot_rng == saved_row.get("rng_file", {}).get("sha256")
            and snapshot_rng == restored_row.get("rng_file", {}).get("sha256")
        )
        dataloader_hash = inventory.get("recover_info/dataloader_info.pkl", {}).get(
            "sha256"
        )
        dataloader_equal = (
            dataloader_hash
            and dataloader_hash == saved_row.get("dataloader_state_sha256")
            and dataloader_hash == restored_row.get("dataloader_state_sha256")
        )
        next_step_equal = (
            int(restored_row.get("saved_global_step", -1))
            == expected_prefix_global_step
            and int(restored_row.get("next_global_step", -1))
            == expected_prefix_global_step + 1
        )
        world_size_equal = (
            int(saved_row.get("world_size", -1)) == snapshot_world_size
            and int(restored_row.get("world_size", -1)) == snapshot_world_size
        )
        engine_load_pass = (
            restored_row.get("dcp_model_optimizer_load") == "PASS"
            and restored_row.get("dataloader_load_state_dict") == "PASS"
        )
        engine_versions_equal = (
            saved_row.get("engine_versions") == restored_row.get("engine_versions")
            and all(
                int(value) == expected_prefix_global_step + 1
                for value in saved_row.get("engine_versions", {}).values()
            )
        )
        audit_rng_restored = saved_row.get("post_audit_rng_restored") is True
        rows.append(
            {
                "rank": rank,
                "rng_hash_equal": bool(rng_equal),
                "dataloader_hash_equal": bool(dataloader_equal),
                "next_step_equal": next_step_equal,
                "world_size_equal": world_size_equal,
                "model_optimizer_and_dataloader_load": engine_load_pass,
                "engine_versions_equal": engine_versions_equal,
                "post_audit_rng_restored": audit_rng_restored,
            }
        )
        if not rng_equal:
            failures.append(f"rng_state_mismatch:rank_{rank}")
        if not dataloader_equal:
            failures.append(f"dataloader_state_mismatch:rank_{rank}")
        if not next_step_equal:
            failures.append(f"recovered_step_mismatch:rank_{rank}")
        if not world_size_equal:
            failures.append(f"world_size_mismatch:rank_{rank}")
        if not engine_load_pass:
            failures.append(f"state_load_not_confirmed:rank_{rank}")
        if not engine_versions_equal:
            failures.append(f"engine_version_mismatch:rank_{rank}")
        if not audit_rng_restored:
            failures.append(f"post_audit_rng_not_restored:rank_{rank}")
    return {
        "status": "PASS" if not failures else "FAIL",
        "expected_prefix_global_step": expected_prefix_global_step,
        "rank_checks": rows,
        "optimizer_state": "DCP_HASH_IDENTICAL_AND_LOAD_COMPLETED",
        "gradient_accumulation_state": "NOT_APPLICABLE_POST_OPTIMIZER_BOUNDARY",
        "amp_scaler_state": "NOT_APPLICABLE_BF16_NO_SCALER",
        "failures": failures,
    }


def summarize_restart_dcp_load(state_continuity: dict[str, Any]) -> dict[str, Any]:
    rank_checks = state_continuity.get("rank_checks", [])
    passed_ranks = [
        int(row["rank"])
        for row in rank_checks
        if row.get("model_optimizer_and_dataloader_load") is True
    ]
    expected_ranks = [int(row["rank"]) for row in rank_checks]
    failures = []
    if not expected_ranks:
        failures.append("restart_load_has_no_rank_evidence")
    if passed_ranks != expected_ranks:
        failures.append("restart_model_optimizer_dataloader_load_incomplete")
    return {
        "status": "PASS" if not failures else "FAIL",
        "kind": "AREAL_DCP_MODEL_OPTIMIZER_AND_DATALOADER_RESTART_LOAD",
        "expected_ranks": expected_ranks,
        "passed_ranks": passed_ranks,
        "failures": failures,
    }


def load_shared_prefix_report(
    path: Path,
    *,
    expected_global_step: int,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if payload.get("schema_version") != "studyhub.sft-shared-prefix.v2":
        failures.append("unexpected_shared_prefix_schema")
    if payload.get("status") != "PASS":
        failures.append("shared_prefix_snapshot_failed")
    step_info = payload.get("step_info")
    if (
        not isinstance(step_info, dict)
        or int(step_info.get("global_step", -1)) != expected_global_step
    ):
        failures.append("shared_prefix_global_step_mismatch")
    if payload.get("method") != "paused_non_destructive_copy_atomic_publish":
        failures.append("shared_prefix_not_non_destructive")
    if payload.get("source_preserved") is not True:
        failures.append("shared_prefix_source_not_preserved")
    if payload.get("inventory_equal") is not True:
        failures.append("shared_prefix_inventory_mismatch")
    source_inventory = payload.get("source_inventory")
    target_inventory = payload.get("target_inventory")
    if not isinstance(source_inventory, dict) or source_inventory != target_inventory:
        failures.append("shared_prefix_hash_provenance_mismatch")
    if payload.get("stability", {}).get("status") != "PASS":
        failures.append("shared_prefix_stability_failed")
    dcp = payload.get("dcp_metadata_load", {})
    if any(dcp.get(side, {}).get("status") != "PASS" for side in ("source", "target")):
        failures.append("shared_prefix_dcp_metadata_load_failed")
    return {
        "status": "PASS" if not failures else "FAIL",
        "path": str(path.resolve()),
        "snapshot": payload,
        "failures": failures,
    }


def compare_run_provenance(reference_path: Path, recovered_path: Path) -> dict[str, Any]:
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    recovered = json.loads(recovered_path.read_text(encoding="utf-8"))

    def summary(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "git_commit": payload.get("git", {}).get("commit"),
            "git_dirty_bytes": payload.get("git", {}).get("dirty_patch_bytes"),
            "config_sha256": payload.get("config", {}).get("sha256"),
            "dataset_manifest_sha256": payload.get("dataset_manifest_sha256"),
            "benchmark_manifest_sha256": payload.get("benchmark", {}).get("sha256"),
            "model_config_sha256": payload.get("model", {}).get("config_sha256"),
            "model_weights": [
                (row.get("name"), row.get("sha256"))
                for row in payload.get("model", {}).get("weight_files", [])
            ],
            "areal_commit": payload.get("areal_upstream", {}).get("commit"),
            "hermes_commit": payload.get("hermes_upstream", {}).get("commit"),
            "software": payload.get("software"),
            "hardware": payload.get("hardware"),
            "exit_status": payload.get("exit_status"),
        }

    left = summary(reference)
    right = summary(recovered)
    compared_keys = (
        "git_commit",
        "config_sha256",
        "dataset_manifest_sha256",
        "benchmark_manifest_sha256",
        "model_config_sha256",
        "model_weights",
        "areal_commit",
        "hermes_commit",
        "software",
        "hardware",
    )
    drift = {
        key: {"reference": left.get(key), "recovered": right.get(key)}
        for key in compared_keys
        if left.get(key) != right.get(key)
    }
    failures = []
    if drift:
        failures.append("run_provenance_drift")
    if left["git_dirty_bytes"] != 0 or right["git_dirty_bytes"] != 0:
        failures.append("run_worktree_not_clean")
    if left["exit_status"] != 0 or right["exit_status"] != 0:
        failures.append("run_exit_status_nonzero")
    return {
        "status": "PASS" if not failures else "FAIL",
        "reference_path": str(reference_path.resolve()),
        "recovered_path": str(recovered_path.resolve()),
        "reference": left,
        "recovered": right,
        "drift": drift,
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
    parser.add_argument("--continuous-audit-root", type=Path, required=True)
    parser.add_argument("--recovered-audit-root", type=Path, required=True)
    parser.add_argument("--continuous-run-metadata", type=Path, required=True)
    parser.add_argument("--recovered-run-metadata", type=Path, required=True)
    parser.add_argument("--boundary-scope", required=True)
    parser.add_argument("--expected-prefix-global-step", type=int, required=True)
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
    shared_prefix = load_shared_prefix_report(
        args.shared_prefix_report,
        expected_global_step=args.expected_prefix_global_step,
    )
    batch_fingerprints = compare_batch_fingerprints(
        args.continuous_audit_root,
        args.recovered_audit_root,
        start=args.tail_start,
        count=args.tail_count,
    )
    state_continuity = verify_state_continuity(
        shared_prefix,
        args.continuous_audit_root,
        args.recovered_audit_root,
        expected_prefix_global_step=args.expected_prefix_global_step,
    )
    run_provenance = compare_run_provenance(
        args.continuous_run_metadata,
        args.recovered_run_metadata,
    )
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
    restart_dcp_load = summarize_restart_dcp_load(state_continuity)
    failures = []
    if continuous_lr["status"] != "PASS":
        failures.append("continuous_lr_contract_failed")
    if recovered_lr["status"] != "PASS":
        failures.append("recovered_lr_contract_failed")
    if shared_prefix["status"] != "PASS":
        failures.append("shared_prefix_contract_failed")
    if run_provenance["status"] != "PASS":
        failures.append("run_provenance_contract_failed")
    if restart_dcp_load["status"] != "PASS":
        failures.append("restart_dcp_load_smoke_failed")
    if state_continuity["status"] != "PASS":
        failures.append("state_continuity_contract_failed")
    if batch_fingerprints["status"] != "PASS":
        failures.append("batch_fingerprint_contract_failed")
    if continuation["status"] != "PASS":
        failures.append("continuation_metrics_contract_failed")
    bounded_contract_eligible = bool(
        contract.get("confirmation", {}).get("eligible_for_promotion", True)
    )
    if adapter["bitwise_equal"]:
        r4_status = "BITWISE_RESUME_PASS"
    elif adapter["status"] == "PASS" and bounded_contract_eligible:
        r4_status = "BOUNDED_NUMERIC_RESUME_PASS"
    else:
        r4_status = "FAIL"
    if r4_status == "FAIL":
        failures.append("recovered_adapter_differs_from_continuous")

    r1 = {
        "status": (
            "PASS"
            if continuous_lr["status"] == recovered_lr["status"] == "PASS"
            else "FAIL"
        ),
        "continuous": continuous_lr,
        "recovered": recovered_lr,
        "recovered_segment_provenance": [
            {
                "origin": "inherited_shared_prefix",
                "start": 0,
                "count": args.tail_start,
            },
            {
                "origin": "recovered_process",
                "start": args.tail_start,
                "count": args.tail_count,
            },
        ],
    }
    r2 = {
        **shared_prefix,
        "status": (
            "PASS"
            if shared_prefix["status"]
            == run_provenance["status"]
            == restart_dcp_load["status"]
            == "PASS"
            else "FAIL"
        ),
        "run_provenance": run_provenance,
        "metadata_parse": shared_prefix.get("snapshot", {}).get(
            "dcp_metadata_load"
        ),
        "actual_restart_load": restart_dcp_load,
    }
    r3 = {
        "status": (
            "PASS"
            if state_continuity["status"]
            == batch_fingerprints["status"]
            == continuation["status"]
            == "PASS"
            else "FAIL"
        ),
        "state_continuity": state_continuity,
        "batch_fingerprints": batch_fingerprints,
        "continuation_metrics": continuation,
        "run_provenance": run_provenance,
    }
    r4 = {
        "status": r4_status,
        "bitwise_equal": adapter["bitwise_equal"],
        "bounded_contract_eligible": bounded_contract_eligible,
        "adapter_comparison": adapter,
    }

    result = {
        "schema_version": "studyhub.sft-recovery-gate.v2",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "PASS" if not failures else "FAIL",
        "claim": (
            "The tested boundary passed R1 LR continuity, R2 checkpoint integrity, "
            "R3 state and exact batch continuity, and R4 final equivalence."
            if not failures
            else "At least one fail-closed R1-R4 recovery contract did not pass."
        ),
        "scope": {
            "model_quality": "NOT_EVALUATED",
            "rl_started": False,
            "sealed_used": False,
            "expected_updates_per_path": args.expected_updates,
            "boundary": args.boundary_scope,
            "formal_training_eligible": not failures
            and args.boundary_scope != "EARLY_WARMUP_MECHANICS_ONLY",
        },
        "equivalence_contract": {
            "path": str(args.equivalence_contract.resolve()),
            "sha256": sha256(args.equivalence_contract),
            "payload": contract,
        },
        "gates": {
            "R1_lr_schedule": r1,
            "R2_snapshot_integrity": r2,
            "R3_state_continuity": r3,
            "R4_final_equivalence": r4,
        },
        "continuous_lr": continuous_lr,
        "recovered_lr": recovered_lr,
        "shared_prefix": shared_prefix,
        "state_continuity": state_continuity,
        "batch_fingerprints": batch_fingerprints,
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
