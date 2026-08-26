#!/usr/bin/env python3
"""Summarize per-rollout and per-GRPO-group Reward v2 diagnostics."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

REWARD_COMPONENTS = (
    "total",
    "task_success",
    "answer_quality",
    "function_call_quality",
    "evidence",
    "citation",
    "tool_quality",
    "efficiency",
)


def _rate(count: int, total: int) -> float:
    return round(count / total, 6) if total else 0.0


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 6) if values else None


def _resolve_log(path: Path) -> Path:
    return path / "reward-v2.jsonl" if path.is_dir() else path


def _distribution(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "mean": round(statistics.fmean(ordered), 6),
        "p95": round(ordered[p95_index], 6),
        "max": round(ordered[-1], 6),
    }


def _runtime_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[float]] = defaultdict(list)
    halt_codes: Counter[str] = Counter()
    runtime_errors: Counter[str] = Counter()
    forced_final_reasons: Counter[str] = Counter()
    halts = 0
    forced_finals = compacted_rollouts = dropped_exchange_rollouts = 0
    compacted_tool_messages = compacted_tool_chars = 0
    counter_failures = guard_failures = 0
    for row in rows:
        trace = row.get("trace", {})
        runtime_errors.update(map(str, trace.get("runtime_errors", [])))
        runtime = trace.get("hermes", {})
        if not isinstance(runtime, dict):
            continue
        for field in ("api_calls", "last_prompt_tokens", "total_tokens"):
            value = runtime.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values[field].append(float(value))
        halt = runtime.get("guardrail_halt")
        if isinstance(halt, dict):
            halts += 1
            halt_codes[str(halt.get("code") or "unknown")] += 1
        context = runtime.get("context_budget")
        if isinstance(context, dict):
            for field in ("max_pre_guard_prompt_tokens", "max_sent_prompt_tokens"):
                value = context.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values[field].append(float(value))
            forced_finals += int(bool(context.get("forced_final")))
            forced_final_reasons.update(
                map(str, context.get("forced_final_reasons", []))
            )
            compacted = int(context.get("compacted_tool_messages", 0) or 0)
            dropped = int(context.get("dropped_tool_exchanges", 0) or 0)
            compacted_rollouts += int(compacted > 0)
            dropped_exchange_rollouts += int(dropped > 0)
            compacted_tool_messages += compacted
            compacted_tool_chars += int(context.get("compacted_tool_chars", 0) or 0)
            counter_failures += int(context.get("counter_failures", 0) or 0)
            guard_failures += int(context.get("guard_failures", 0) or 0)
    return {
        "api_calls": _distribution(values["api_calls"]),
        "last_prompt_tokens": _distribution(values["last_prompt_tokens"]),
        "total_tokens": _distribution(values["total_tokens"]),
        "guardrail_halts": halts,
        "guardrail_halt_rate": _rate(halts, len(rows)),
        "guardrail_halt_codes": dict(sorted(halt_codes.items())),
        "context_budget": {
            "max_pre_guard_prompt_tokens": _distribution(
                values["max_pre_guard_prompt_tokens"]
            ),
            "max_sent_prompt_tokens": _distribution(values["max_sent_prompt_tokens"]),
            "forced_final_rollouts": forced_finals,
            "forced_final_rate": _rate(forced_finals, len(rows)),
            "forced_final_reasons": dict(sorted(forced_final_reasons.items())),
            "compacted_rollouts": compacted_rollouts,
            "compacted_rollout_rate": _rate(compacted_rollouts, len(rows)),
            "compacted_tool_messages": compacted_tool_messages,
            "compacted_tool_chars": compacted_tool_chars,
            "dropped_exchange_rollouts": dropped_exchange_rollouts,
            "counter_failures": counter_failures,
            "guard_failures": guard_failures,
            "runtime_errors": dict(sorted(runtime_errors.items())),
        },
    }


def _slice_summary(
    rows: list[dict[str, Any]], *, expected_group_size: int
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    components: dict[str, list[float]] = defaultdict(list)
    violations: Counter[str] = Counter()
    empty_answers = invalid_rollouts = no_tool_rollouts = hard_gates = 0
    for row in rows:
        groups[str(row.get("rollout_group_id") or row["task_id"])].append(row)
        reward = row["reward"]
        for component in REWARD_COMPONENTS:
            value = reward.get(component)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                components[component].append(float(value))
        violations.update(map(str, reward.get("violations", [])))
        trace = row.get("trace", {})
        empty_answers += int(bool(row.get("final_answer_empty")))
        invalid_rollouts += int(int(trace.get("invalid_tool_calls", 0)) > 0)
        no_tool_rollouts += int(int(trace.get("tool_calls", 0)) == 0)
        hard_gates += int(bool(reward.get("hard_gate_triggered")))

    complete = [group for group in groups.values() if len(group) == expected_group_size]
    group_stds = [
        statistics.pstdev(float(row["reward"]["total"]) for row in group)
        for group in complete
    ]
    totals = components["total"]
    zero_variance = sum(value <= 1e-12 for value in group_stds)
    return {
        "rollouts": len(rows),
        "groups": len(groups),
        "complete_groups": len(complete),
        "incomplete_groups": len(groups) - len(complete),
        "zero_variance_group_rate": _rate(zero_variance, len(complete)),
        "mean_group_reward_std": _mean(group_stds),
        "reward": {
            "mean": _mean(totals),
            "std": round(statistics.pstdev(totals), 6) if totals else None,
            "min": round(min(totals), 6) if totals else None,
            "max": round(max(totals), 6) if totals else None,
            "component_means": {
                component: _mean(values)
                for component, values in sorted(components.items())
            },
        },
        "quality_rates": {
            "empty_final_answer": _rate(empty_answers, len(rows)),
            "invalid_tool_call": _rate(invalid_rollouts, len(rows)),
            "no_tool_call": _rate(no_tool_rollouts, len(rows)),
            "hard_gate": _rate(hard_gates, len(rows)),
        },
        "runtime": _runtime_summary(rows),
        "violations": dict(sorted(violations.items())),
    }


def summarize(path: Path, *, expected_group_size: int) -> dict[str, Any]:
    log_path = _resolve_log(path)
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"reward log is empty: {log_path}")

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    families: Counter[str] = Counter()
    violations: Counter[str] = Counter()
    rollout_ids: Counter[str] = Counter()
    component_values: dict[str, list[float]] = defaultdict(list)
    empty_answers = invalid_rollouts = no_tool_rollouts = hard_gates = 0

    for row in rows:
        group_id = str(row.get("rollout_group_id") or row["task_id"])
        groups[group_id].append(row)
        families[str(row.get("task_family") or "unknown")] += 1
        rollout_ids[str(row.get("rollout_id") or "missing")] += 1
        reward = row["reward"]
        for component in REWARD_COMPONENTS:
            value = reward.get(component)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                component_values[component].append(float(value))
        violations.update(map(str, reward.get("violations", [])))
        trace = row.get("trace", {})
        empty_answers += int(bool(row.get("final_answer_empty")))
        invalid_rollouts += int(int(trace.get("invalid_tool_calls", 0)) > 0)
        no_tool_rollouts += int(int(trace.get("tool_calls", 0)) == 0)
        hard_gates += int(bool(reward.get("hard_gate_triggered")))

    group_sizes = Counter(len(group) for group in groups.values())
    complete_groups = [group for group in groups.values() if len(group) == expected_group_size]
    group_stds = [statistics.pstdev(float(row["reward"]["total"]) for row in group) for group in complete_groups]
    zero_variance = sum(value <= 1e-12 for value in group_stds)
    totals = component_values["total"]
    duplicate_rollouts = sum(count - 1 for count in rollout_ids.values() if count > 1)
    family_summaries = {
        family: _slice_summary(
            [row for row in rows if str(row.get("task_family") or "unknown") == family],
            expected_group_size=expected_group_size,
        )
        for family in sorted(families)
    }

    return {
        "schema_version": "studyhub.reward-diagnostics.v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "artifact": str(log_path.resolve()),
        "experiments": sorted({str(row.get("experiment_name", "unknown")) for row in rows}),
        "trials": sorted({str(row.get("trial_name", "unknown")) for row in rows}),
        "rollouts": len(rows),
        "unique_rollout_ids": len(rollout_ids),
        "duplicate_rollout_ids": duplicate_rollouts,
        "groups": len(groups),
        "expected_group_size": expected_group_size,
        "group_size_counts": {str(size): count for size, count in sorted(group_sizes.items())},
        "complete_groups": len(complete_groups),
        "incomplete_groups": len(groups) - len(complete_groups),
        "zero_variance_complete_groups": zero_variance,
        "zero_variance_group_rate": _rate(zero_variance, len(complete_groups)),
        "mean_group_reward_std": _mean(group_stds),
        "reward": {
            "mean": _mean(totals),
            "std": round(statistics.pstdev(totals), 6),
            "min": round(min(totals), 6),
            "max": round(max(totals), 6),
            "component_means": {component: _mean(values) for component, values in sorted(component_values.items())},
        },
        "quality_rates": {
            "empty_final_answer": _rate(empty_answers, len(rows)),
            "invalid_tool_call": _rate(invalid_rollouts, len(rows)),
            "no_tool_call": _rate(no_tool_rollouts, len(rows)),
            "hard_gate": _rate(hard_gates, len(rows)),
        },
        "runtime": _runtime_summary(rows),
        "families": dict(sorted(families.items())),
        "by_family": family_summaries,
        "violations": dict(sorted(violations.items())),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="reward-v2.jsonl or its trial directory")
    parser.add_argument("--expected-group-size", type=int, default=4)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.expected_group_size < 1:
        parser.error("--expected-group-size must be positive")
    return args


def main() -> int:
    args = parse_args()
    result = summarize(args.path, expected_group_size=args.expected_group_size)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
