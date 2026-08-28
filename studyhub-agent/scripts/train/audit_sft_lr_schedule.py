#!/usr/bin/env python3
"""Audit one or more SFT metric segments against an exact cosine LR contract."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def expected_cosine_lr(
    step: int,
    *,
    base_lr: float,
    total_steps: int,
    warmup_fraction: float,
    min_lr_ratio: float = 0.0,
) -> float:
    warmup_steps = int(warmup_fraction * total_steps)
    if step < warmup_steps:
        ratio = min_lr_ratio + (1.0 - min_lr_ratio) * (float(step) / float(max(1, warmup_steps)))
    else:
        progress = float(step - warmup_steps) / float(max(1, total_steps - warmup_steps))
        coefficient = (1.0 - min_lr_ratio) * 0.5
        intercept = (1.0 + min_lr_ratio) * 0.5
        ratio = max(min_lr_ratio, math.cos(math.pi * progress) * coefficient + intercept)
    return base_lr * ratio


def parse_segment(value: str) -> tuple[Path, int, int]:
    try:
        path_value, start_value, count_value = value.rsplit(",", 2)
        path = Path(path_value)
        start = int(start_value)
        count = int(count_value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("segment must use METRICS_JSON,START_GLOBAL_STEP,COUNT") from exc
    if start < 0 or count <= 0:
        raise argparse.ArgumentTypeError("segment start must be >=0 and count must be >0")
    return path, start, count


def load_lr_series(path: Path) -> list[float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("series", {}).get("sft/lr")
    if not isinstance(values, list) or not values:
        raise RuntimeError(f"missing sft/lr series: {path}")
    return [float(value) for value in values]


def audit(
    segments: list[tuple[Path, int, int]],
    *,
    base_lr: float,
    total_steps: int,
    warmup_fraction: float,
    expected_updates: int,
    expected_start_step: int = 0,
    rel_tolerance: float = 1e-4,
    abs_tolerance: float = 5e-10,
) -> dict[str, Any]:
    failures: list[str] = []
    segment_results: list[dict[str, Any]] = []
    covered_steps: list[int] = []
    all_mismatches = 0

    for path, start, count in segments:
        values = load_lr_series(path)
        if len(values) < count:
            failures.append(f"segment_too_short:{path}:{len(values)}<{count}")
            count = len(values)
        mismatches: list[dict[str, Any]] = []
        max_absolute_error = 0.0
        max_relative_error = 0.0
        for offset, actual in enumerate(values[:count]):
            global_step = start + offset
            expected = expected_cosine_lr(
                global_step,
                base_lr=base_lr,
                total_steps=total_steps,
                warmup_fraction=warmup_fraction,
            )
            absolute_error = abs(actual - expected)
            relative_error = absolute_error / max(abs(expected), abs_tolerance)
            max_absolute_error = max(max_absolute_error, absolute_error)
            max_relative_error = max(max_relative_error, relative_error)
            if not math.isclose(
                actual,
                expected,
                rel_tol=rel_tolerance,
                abs_tol=abs_tolerance,
            ):
                if len(mismatches) < 5:
                    mismatches.append(
                        {
                            "global_step": global_step,
                            "actual": actual,
                            "expected": expected,
                            "absolute_error": absolute_error,
                        }
                    )
                all_mismatches += 1
            covered_steps.append(global_step)
        segment_results.append(
            {
                "metrics": str(path),
                "start_global_step": start,
                "count": count,
                "first_actual_lr": values[0],
                "last_actual_lr": values[count - 1],
                "first_expected_lr": expected_cosine_lr(
                    start,
                    base_lr=base_lr,
                    total_steps=total_steps,
                    warmup_fraction=warmup_fraction,
                ),
                "last_expected_lr": expected_cosine_lr(
                    start + count - 1,
                    base_lr=base_lr,
                    total_steps=total_steps,
                    warmup_fraction=warmup_fraction,
                ),
                "mismatch_count": sum(
                    not math.isclose(
                        values[offset],
                        expected_cosine_lr(
                            start + offset,
                            base_lr=base_lr,
                            total_steps=total_steps,
                            warmup_fraction=warmup_fraction,
                        ),
                        rel_tol=rel_tolerance,
                        abs_tol=abs_tolerance,
                    )
                    for offset in range(count)
                ),
                "first_mismatches": mismatches,
                "max_absolute_error": max_absolute_error,
                "max_relative_error": max_relative_error,
            }
        )

    expected_coverage = list(
        range(expected_start_step, expected_start_step + expected_updates)
    )
    if covered_steps != expected_coverage:
        failures.append("global_step_coverage_not_exact")
    if all_mismatches:
        failures.append(f"lr_schedule_mismatches:{all_mismatches}")

    return {
        "schema_version": "studyhub.sft-lr-schedule-audit.v1",
        "status": "PASS" if not failures else "FAIL",
        "contract": {
            "base_lr": base_lr,
            "scheduler": "cosine",
            "scheduler_total_steps": total_steps,
            "warmup_fraction": warmup_fraction,
            "warmup_steps": int(warmup_fraction * total_steps),
            "expected_updates": expected_updates,
            "expected_start_step": expected_start_step,
            "rel_tolerance": rel_tolerance,
            "abs_tolerance": abs_tolerance,
        },
        "segments": segment_results,
        "coverage": {
            "observed_updates": len(covered_steps),
            "first_global_step": covered_steps[0] if covered_steps else None,
            "last_global_step": covered_steps[-1] if covered_steps else None,
        },
        "mismatch_count": all_mismatches,
        "failures": failures,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--segment",
        action="append",
        type=parse_segment,
        required=True,
        help="METRICS_JSON,START_GLOBAL_STEP,COUNT; repeat for resumed runs",
    )
    parser.add_argument("--base-lr", type=float, required=True)
    parser.add_argument("--scheduler-total-steps", type=int, required=True)
    parser.add_argument("--warmup-fraction", type=float, required=True)
    parser.add_argument("--expected-updates", type=int, required=True)
    parser.add_argument("--expected-start-step", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = audit(
        args.segment,
        base_lr=args.base_lr,
        total_steps=args.scheduler_total_steps,
        warmup_fraction=args.warmup_fraction,
        expected_updates=args.expected_updates,
        expected_start_step=args.expected_start_step,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
