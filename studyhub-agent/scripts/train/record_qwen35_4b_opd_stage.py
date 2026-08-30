#!/usr/bin/env python3
"""Validate and record one strict OPD LR pilot, pilot, or formal stage."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

from scripts.train.record_formal_sft_completion import final_adapter, sha256
from scripts.train.record_qwen35_4b_sft2_completion import exact_adapter_match


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def series(payload: dict[str, Any], name: str) -> list[float]:
    values = payload.get("series", {}).get(name)
    if values is None:
        matching = [
            value
            for key, value in payload.get("series", {}).items()
            if key.endswith("/" + name)
        ]
        if len(matching) != 1:
            raise RuntimeError(f"missing or ambiguous trainer metric: {name}")
        values = matching[0]
    result = [float(value) for value in values]
    if not result or not all(math.isfinite(value) for value in result):
        raise RuntimeError(f"non-finite or empty trainer metric: {name}")
    return result


def optional_series(payload: dict[str, Any], name: str) -> list[float]:
    try:
        return series(payload, name)
    except RuntimeError:
        return []


def reward_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(root.rglob("reward-v3.jsonl")):
        with path.open(encoding="utf-8") as stream:
            rows.extend(json.loads(line) for line in stream if line.strip())
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("lr1e6", "lr3e6", "pilot", "formal"), required=True
    )
    parser.add_argument("--trainer-metrics", type=Path, required=True)
    parser.add_argument("--reward-root", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--learning-rate", type=float, required=True)
    parser.add_argument("--expected-updates", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    authorization = load_json(args.authorization)
    metrics = load_json(args.trainer_metrics)
    opd_loss = series(metrics, "opd_loss")
    overlap = series(metrics, "opd_overlap_ratio")
    advantage = series(metrics, "opd_teacher_logprob_advantage")
    scored_tokens = series(metrics, "opd_scored_tokens")
    grad_norm = series(metrics, "grad_norm")
    update_success = optional_series(metrics, "update_successful")
    no_eos = optional_series(metrics, "no_eos_ratios/avg")
    seq_len = optional_series(metrics, "seq_len/avg")
    if any(
        len(values) != args.expected_updates
        for values in (opd_loss, overlap, advantage, scored_tokens, grad_norm)
    ):
        raise RuntimeError(
            "OPD trainer metric coverage does not match expected updates"
        )
    if update_success and (
        len(update_success) != args.expected_updates
        or any(value != 1.0 for value in update_success)
    ):
        raise RuntimeError("one or more OPD optimizer updates failed")

    rewards = reward_rows(args.reward_root)
    if not rewards:
        raise RuntimeError("OPD run has no Reward v3 trajectory evidence")
    scored_rewards = [
        row for row in rewards if row.get("reward", {}).get("status") == "SCORED"
    ]
    if len(scored_rewards) != len(rewards):
        raise RuntimeError("OPD run contains non-scored rollout evidence")
    tool_validity = [float(row["reward"]["tool_validity"]) for row in scored_rewards]
    hard_gates = [bool(row["reward"]["hard_gate_triggered"]) for row in scored_rewards]

    m2_weights = (
        Path(authorization["lineage"]["m2_adapter_path"]) / "adapter_model.safetensors"
    )
    initial = args.checkpoint_root / "actor/initial_lora/adapter_model.safetensors"
    initialization = exact_adapter_match(initial, m2_weights)
    if initialization["status"] != "PASS":
        raise RuntimeError("OPD actor did not initialize exactly from M2")
    final_step, final_weights = final_adapter(args.checkpoint_root)
    if final_step != args.expected_updates - 1:
        raise RuntimeError(
            f"OPD checkpoint stopped at global step {final_step}; expected {args.expected_updates - 1}"
        )
    if sha256(final_weights) == sha256(initial):
        raise RuntimeError("OPD LoRA adapter did not update")

    mean = lambda values: sum(values) / len(values)  # noqa: E731
    mean_overlap = mean(overlap)
    mean_advantage = mean(advantage)
    mean_tool_validity = mean(tool_validity)
    mean_no_eos = mean(no_eos) if no_eos else None
    mean_seq_len = mean(seq_len) if seq_len else None
    baseline_tool_validity = float(
        authorization["hard_gates"]["student_baseline_tool_validity"]
    )
    failures = []
    if mean_overlap <= 0:
        failures.append("no_teacher_student_topk_overlap")
    if max(abs(value) for value in advantage) <= 1.0e-6:
        failures.append("teacher_signal_indistinguishable_from_zero")
    if max(grad_norm) <= 0:
        failures.append("zero_grad_norm")
    if args.mode in {"pilot", "formal"}:
        if mean_advantage <= 0:
            failures.append("nonpositive_teacher_logprob_advantage")
        if mean_tool_validity < baseline_tool_validity - 0.05:
            failures.append("tool_validity_collapse")
        if mean_no_eos is None or mean_no_eos >= 0.05:
            failures.append("truncation_rate_too_high_or_missing")
        if mean_seq_len is None or mean_seq_len > 4096:
            failures.append("sequence_length_invalid_or_missing")
    status = {
        "lr1e6": "PASS_OPD_LR_MICRO_PILOT",
        "lr3e6": "PASS_OPD_LR_MICRO_PILOT",
        "pilot": "OPD_PILOT_PASS",
        "formal": "OPD_COMPLETE",
    }[args.mode]
    if failures:
        status = "OPD_PILOT_FAILED" if args.mode != "formal" else "OPD_FORMAL_FAILED"
    result = {
        "schema_version": "studyhub.qwen35-4b-opd-stage.v1",
        "status": status,
        "mode": args.mode,
        "learning_rate": args.learning_rate,
        "optimizer_updates": args.expected_updates,
        "rollout_rows": len(rewards),
        "metrics": {
            "opd_loss_mean": mean(opd_loss),
            "opd_loss_final": opd_loss[-1],
            "grad_norm_mean": mean(grad_norm),
            "grad_norm_max": max(grad_norm),
            "teacher_student_overlap_mean": mean_overlap,
            "teacher_logprob_advantage_mean": mean_advantage,
            "teacher_scored_tokens": int(sum(scored_tokens)),
            "tool_validity_mean": mean_tool_validity,
            "hard_gate_rate": sum(hard_gates) / len(hard_gates),
            "no_eos_rate_mean": mean_no_eos,
            "sequence_length_mean": mean_seq_len,
        },
        "initialization": initialization,
        "checkpoint": {
            "global_step": final_step,
            "path": str(final_weights.resolve()),
            "sha256": sha256(final_weights),
            "lora_updated": True,
        },
        "failures": failures,
        "authorization_sha256": sha256(args.authorization),
        "trainer_metrics_sha256": sha256(args.trainer_metrics),
        "sealed_used": False,
        "main_grpo_started": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 3


if __name__ == "__main__":
    raise SystemExit(main())
