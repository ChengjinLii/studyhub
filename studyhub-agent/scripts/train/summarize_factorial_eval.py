#!/usr/bin/env python3
"""Summarize the controlled Base/SFT/RL 2x2 evaluation with paired bootstrap."""

from __future__ import annotations

import argparse
import json
import random
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


DEFAULT_LABELS = {
    "base": "base4b",
    "sft": "sft4b",
    "rl": "direct_rl4b",
    "sft_rl": "sft_rl4b",
}
METRICS: dict[str, Callable[[dict[str, Any]], float]] = {
    "strict_success_rate": lambda row: float(row["strict_success_rate"]),
    "pass_at_4": lambda row: float(row["pass_at_4"]),
    "consistent_at_4": lambda row: float(row["consistent_at_4"]),
    "mean_reward": lambda row: float(row["mean_reward"]),
}
OVERALL_METRIC_KEYS = {
    "strict_success_rate": "strict_rollout_success_rate",
    "pass_at_4": "pass_at_4",
    "consistent_at_4": "consistent_at_4",
    "mean_reward": "mean_reward",
}


def _paired_rows(
    runs: dict[str, Any], labels: dict[str, str]
) -> list[dict[str, dict[str, Any]]]:
    indexed: dict[str, dict[str, dict[str, Any]]] = {}
    for role, label in labels.items():
        if label not in runs:
            raise ValueError(f"missing run label for {role}: {label}")
        rows = runs[label].get("per_task", [])
        by_id = {str(row["task_id"]): row for row in rows}
        if len(by_id) != len(rows):
            raise ValueError(f"duplicate task IDs in run: {label}")
        indexed[role] = by_id

    task_sets = {role: set(rows) for role, rows in indexed.items()}
    reference = task_sets["base"]
    if any(task_ids != reference for task_ids in task_sets.values()):
        counts = {role: len(task_ids) for role, task_ids in task_sets.items()}
        raise ValueError(f"factorial runs do not share task IDs: {counts}")
    if not reference:
        raise ValueError("factorial evaluation contains no tasks")

    return [
        {role: indexed[role][task_id] for role in labels}
        for task_id in sorted(reference)
    ]


def _contrasts(values: dict[str, float]) -> dict[str, float]:
    base = values["base"]
    sft = values["sft"]
    rl = values["rl"]
    sft_rl = values["sft_rl"]
    return {
        "sft_without_rl": sft - base,
        "rl_without_sft": rl - base,
        "rl_after_sft": sft_rl - sft,
        "sft_after_rl": sft_rl - rl,
        "interaction": sft_rl - rl - sft + base,
    }


def _percentile(sorted_values: list[float], quantile: float) -> float:
    index = int((len(sorted_values) - 1) * quantile)
    return sorted_values[index]


def summarize_factorial(
    payload: dict[str, Any],
    labels: dict[str, str] | None = None,
    *,
    bootstrap_samples: int = 10_000,
    seed: int = 6209,
) -> dict[str, Any]:
    if bootstrap_samples < 1:
        raise ValueError("bootstrap_samples must be positive")
    resolved_labels = dict(DEFAULT_LABELS if labels is None else labels)
    if set(resolved_labels) != set(DEFAULT_LABELS):
        raise ValueError(f"labels must define exactly: {sorted(DEFAULT_LABELS)}")
    paired = _paired_rows(payload["runs"], resolved_labels)
    task_count = len(paired)
    rng = random.Random(seed)

    metric_results: dict[str, Any] = {}
    for metric, extractor in METRICS.items():
        per_task = [
            _contrasts({role: extractor(row) for role, row in task_rows.items()})
            for task_rows in paired
        ]
        contrast_names = tuple(per_task[0])
        samples: dict[str, list[float]] = {name: [] for name in contrast_names}
        for _ in range(bootstrap_samples):
            selected = [rng.randrange(task_count) for _ in range(task_count)]
            for name in contrast_names:
                samples[name].append(
                    statistics.fmean(per_task[index][name] for index in selected)
                )

        metric_results[metric] = {}
        for name in contrast_names:
            ordered = sorted(samples[name])
            point = statistics.fmean(row[name] for row in per_task)
            metric_results[metric][name] = {
                "estimate": point,
                "ci95": [
                    _percentile(ordered, 0.025),
                    _percentile(ordered, 0.975),
                ],
                "supports_nonzero_effect": not (
                    _percentile(ordered, 0.025)
                    <= 0.0
                    <= _percentile(ordered, 0.975)
                ),
            }

    matrix = {}
    for role, label in resolved_labels.items():
        overall = payload["runs"][label]["overall"]
        matrix[role] = {
            "label": label,
            **{
                metric: float(overall[OVERALL_METRIC_KEYS[metric]])
                for metric in METRICS
            },
        }

    return {
        "schema_version": "studyhub.factorial-eval.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_schema_version": payload.get("schema_version"),
        "task_count": task_count,
        "bootstrap_samples": bootstrap_samples,
        "seed": seed,
        "labels": resolved_labels,
        "matrix": matrix,
        "contrasts": metric_results,
        "interpretation": {
            "interaction": "B3 - B2 - B1 + B0",
            "rule": "Treat a contrast as directional evidence only when its paired 95% bootstrap CI excludes zero.",
            "scope": "Eval32 is a verifier-aligned development set, not a sealed final benchmark.",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base", default=DEFAULT_LABELS["base"])
    parser.add_argument("--sft", default=DEFAULT_LABELS["sft"])
    parser.add_argument("--rl", default=DEFAULT_LABELS["rl"])
    parser.add_argument("--sft-rl", default=DEFAULT_LABELS["sft_rl"])
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=6209)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = summarize_factorial(
        payload,
        {
            "base": args.base,
            "sft": args.sft,
            "rl": args.rl,
            "sft_rl": args.sft_rl,
        },
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
