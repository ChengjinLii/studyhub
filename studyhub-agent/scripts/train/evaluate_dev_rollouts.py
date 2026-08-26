#!/usr/bin/env python3
"""Evaluate fixed development rollouts with a strict, non-scalar protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROTOCOL = {
    "schema_version": "studyhub.dev-eval.v1",
    "scope": "verifier-aligned development evaluation; not a sealed final test",
    "strict_success": {
        "all": ["nonempty final answer", "no hard gate", "no violations"],
        "function_calling": [
            "function_call_quality == 1",
            "answer_quality >= 0.8",
            "tool_quality == 1",
        ],
        "search_or_grounding": [
            "task_success == 1",
            "evidence == 1",
            "citation == 1",
            "tool_quality == 1",
        ],
    },
    "group_metrics": [
        "strict rollout success rate",
        "pass@4 (at least one strict success)",
        "consistent@4 (all four strict successes)",
    ],
    "caveat": "The protocol uses hidden verifier components but not scalar reward thresholds; a separate sealed benchmark is still required for final claims.",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _strict_success(row: dict[str, Any]) -> bool:
    reward = row["reward"]
    if row.get("final_answer_empty"):
        return False
    if reward.get("hard_gate_triggered") or reward.get("violations"):
        return False
    if float(reward.get("tool_quality", 0.0)) < 0.999:
        return False
    if row["task_family"] == "function_calling":
        return (
            float(reward.get("function_call_quality") or 0.0) >= 0.999
            and float(reward.get("answer_quality", 0.0)) >= 0.8
        )
    return (
        float(reward.get("task_success", 0.0)) >= 0.999
        and float(reward.get("evidence", 0.0)) >= 0.999
        and float(reward.get("citation", 0.0)) >= 0.999
    )


def _read_rows(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise RuntimeError(f"empty reward log: {path}")
    if any(row.get("split") != "validation" for row in rows):
        raise RuntimeError(f"development evaluation contains non-validation rows: {path}")
    rollout_ids = [str(row["rollout_id"]) for row in rows]
    if len(rollout_ids) != len(set(rollout_ids)):
        raise RuntimeError(f"duplicate rollout IDs: {path}")
    return rows


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_task[str(row["task_id"])].append(row)
    group_sizes = Counter(len(group) for group in by_task.values())
    per_task = []
    for task_id, group in sorted(by_task.items()):
        strict = [_strict_success(row) for row in group]
        totals = [float(row["reward"]["total"]) for row in group]
        per_task.append(
            {
                "task_id": task_id,
                "family": group[0]["task_family"],
                "source_dataset": group[0]["source_dataset"],
                "rollouts": len(group),
                "strict_successes": sum(strict),
                "strict_success_rate": sum(strict) / len(strict),
                "pass_at_4": any(strict),
                "consistent_at_4": all(strict),
                "mean_reward": statistics.fmean(totals),
            }
        )

    def aggregate(task_rows: list[dict[str, Any]], rollout_rows: list[dict[str, Any]]) -> dict[str, Any]:
        strict = [_strict_success(row) for row in rollout_rows]
        reward_totals = [float(row["reward"]["total"]) for row in rollout_rows]
        violations = Counter(
            violation
            for row in rollout_rows
            for violation in row["reward"].get("violations", [])
        )
        return {
            "tasks": len(task_rows),
            "rollouts": len(rollout_rows),
            "strict_rollout_success_rate": sum(strict) / len(strict),
            "pass_at_4": sum(bool(row["pass_at_4"]) for row in task_rows) / len(task_rows),
            "consistent_at_4": sum(bool(row["consistent_at_4"]) for row in task_rows) / len(task_rows),
            "mean_reward": statistics.fmean(reward_totals),
            "reward_std": statistics.pstdev(reward_totals),
            "hard_gate_rate": sum(
                bool(row["reward"].get("hard_gate_triggered")) for row in rollout_rows
            )
            / len(rollout_rows),
            "mean_tool_calls": statistics.fmean(
                float(row["trace"].get("tool_calls", 0)) for row in rollout_rows
            ),
            "mean_total_tokens": statistics.fmean(
                float(row["trace"].get("hermes", {}).get("total_tokens", 0))
                for row in rollout_rows
            ),
            "violations": dict(sorted(violations.items())),
        }

    by_family = {}
    for family in sorted({row["task_family"] for row in rows}):
        family_rollouts = [row for row in rows if row["task_family"] == family]
        family_tasks = [row for row in per_task if row["family"] == family]
        by_family[family] = aggregate(family_tasks, family_rollouts)
    return {
        "group_size_counts": {str(key): value for key, value in sorted(group_sizes.items())},
        "overall": aggregate(per_task, rows),
        "by_family": by_family,
        "per_task": per_task,
    }


def _paired_bootstrap(values: list[float], seed: int = 6209) -> dict[str, Any]:
    if not values:
        return {"mean": None, "ci95": [None, None], "tasks": 0}
    rng = random.Random(seed)
    means = []
    for _ in range(10_000):
        means.append(statistics.fmean(rng.choice(values) for _ in values))
    means.sort()
    return {
        "mean": statistics.fmean(values),
        "ci95": [means[249], means[9749]],
        "tasks": len(values),
        "bootstrap_samples": 10_000,
        "seed": seed,
    }


def compare_runs(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    base_tasks = {row["task_id"]: row for row in baseline["per_task"]}
    candidate_tasks = {row["task_id"]: row for row in candidate["per_task"]}
    if set(base_tasks) != set(candidate_tasks):
        raise RuntimeError("paired evaluation task IDs differ")
    task_ids = sorted(base_tasks)
    reward_delta = [
        candidate_tasks[task_id]["mean_reward"] - base_tasks[task_id]["mean_reward"]
        for task_id in task_ids
    ]
    strict_delta = [
        candidate_tasks[task_id]["strict_success_rate"]
        - base_tasks[task_id]["strict_success_rate"]
        for task_id in task_ids
    ]
    pass_delta = [
        float(candidate_tasks[task_id]["pass_at_4"])
        - float(base_tasks[task_id]["pass_at_4"])
        for task_id in task_ids
    ]
    return {
        "paired_tasks": len(task_ids),
        "candidate_minus_baseline": {
            "mean_reward": _paired_bootstrap(reward_delta),
            "strict_success_rate": _paired_bootstrap(strict_delta),
            "pass_at_4": _paired_bootstrap(pass_delta),
        },
        "task_outcomes": {
            "strict_improved": sum(delta > 0 for delta in strict_delta),
            "strict_unchanged": sum(delta == 0 for delta in strict_delta),
            "strict_regressed": sum(delta < 0 for delta in strict_delta),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="LABEL=REWARD_JSONL",
        help="Add one development-evaluation reward log.",
    )
    parser.add_argument("--baseline")
    parser.add_argument("--candidate")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_paths: dict[str, Path] = {}
    for item in args.run:
        if "=" not in item:
            raise ValueError(f"invalid --run value: {item}")
        label, raw_path = item.split("=", 1)
        if not label or label in run_paths:
            raise ValueError(f"invalid or duplicate run label: {label}")
        run_paths[label] = Path(raw_path).resolve()

    runs = {}
    for label, path in run_paths.items():
        summary = _summarize_rows(_read_rows(path))
        runs[label] = {
            "reward_log": str(path),
            "reward_log_sha256": _sha256(path),
            **summary,
        }
    result: dict[str, Any] = {
        "schema_version": "studyhub.dev-eval-results.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "protocol": PROTOCOL,
        "runs": runs,
    }
    if args.baseline or args.candidate:
        if not args.baseline or not args.candidate:
            raise ValueError("--baseline and --candidate must be provided together")
        result["comparison"] = {
            "baseline": args.baseline,
            "candidate": args.candidate,
            **compare_runs(runs[args.baseline], runs[args.candidate]),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
