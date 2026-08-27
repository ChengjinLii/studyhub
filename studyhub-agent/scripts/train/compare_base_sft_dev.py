#!/usr/bin/env python3
"""Compare paired Base and SFT Benchmark v2 Development episodes."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = {}
    for row in rows:
        if row.get("status") != "SCORED":
            continue
        task_id = str(row["task_id"])
        if task_id in result:
            raise RuntimeError(f"duplicate scored Development task: {task_id}")
        result[task_id] = row
    return result


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def paired_bootstrap(
    task_ids: list[str],
    difference: Callable[[str], float],
    *,
    seed: int,
    samples: int = 10_000,
) -> dict[str, Any]:
    rng = random.Random(seed)
    observed = statistics.fmean(difference(task_id) for task_id in task_ids)
    draws = []
    for _ in range(samples):
        draws.append(statistics.fmean(difference(rng.choice(task_ids)) for _ in task_ids))
    return {
        "point": round(observed, 6),
        "ci95": [round(percentile(draws, 0.025), 6), round(percentile(draws, 0.975), 6)],
        "bootstrap_samples": samples,
        "seed": seed,
    }


def hard_gate_counts(rows: dict[str, dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows.values():
        counts.update(str(reason) for reason in row.get("evaluation", {}).get("hard_gate_reasons", []))
        trace = row.get("trace", {})
        counts.update(f"environment:{value}" for value in trace.get("environment_errors", []))
        counts.update(f"policy:{value}" for value in trace.get("policy_errors", []))
        counts.update(f"runtime:{value}" for value in trace.get("runtime_errors", []))
    return counts


def metric(row: dict[str, Any], name: str) -> float:
    evaluation = row.get("evaluation", {})
    if name == "strict_success":
        return float(bool(evaluation.get("strict_success")))
    if name == "diagnostic":
        return float(evaluation.get("diagnostic_scalar", 0.0))
    if name == "tool_validity":
        return float(evaluation.get("tool_validity", 0.0))
    if name == "tool_calls":
        return float(evaluation.get("tool_calls", 0.0))
    raise ValueError(name)


def compare(base_dir: Path, sft_dir: Path, *, seed: int) -> dict[str, Any]:
    base_summary = json.loads((base_dir / "summary.json").read_text(encoding="utf-8"))
    sft_summary = json.loads((sft_dir / "summary.json").read_text(encoding="utf-8"))
    base_path = base_dir / "episodes.jsonl"
    sft_path = sft_dir / "episodes.jsonl"
    base = load_jsonl(base_path)
    sft = load_jsonl(sft_path)
    failures = []
    if base_summary.get("mode") != "development" or sft_summary.get("mode") != "development":
        failures.append("mode_not_development")
    if base_summary.get("benchmark_manifest_sha256") != sft_summary.get("benchmark_manifest_sha256"):
        failures.append("benchmark_hash_mismatch")
    if float(base_summary.get("temperature", -1)) != 0.0 or float(sft_summary.get("temperature", -1)) != 0.0:
        failures.append("temperature_not_zero")
    if int(base_summary.get("infra_excluded", -1)) or int(sft_summary.get("infra_excluded", -1)):
        failures.append("infra_exclusions_present")
    if set(base) != set(sft):
        failures.append("paired_task_set_mismatch")
    task_ids = sorted(set(base) & set(sft))
    if len(task_ids) != 51:
        failures.append(f"paired_task_count:{len(task_ids)}")
    sealed_rows = sum(
        bool(row.get("evaluation", {}).get("diagnostics", {}).get("sealed"))
        for row in [*base.values(), *sft.values()]
    )
    if sealed_rows:
        failures.append(f"sealed_rows:{sealed_rows}")

    strict_pairs = [(metric(base[key], "strict_success"), metric(sft[key], "strict_success")) for key in task_ids]
    wins = sum(before == 0 and after == 1 for before, after in strict_pairs)
    losses = sum(before == 1 and after == 0 for before, after in strict_pairs)
    ties = len(strict_pairs) - wins - losses
    family: dict[str, dict[str, Any]] = {}
    family_tasks: dict[str, list[str]] = defaultdict(list)
    for task_id in task_ids:
        family_tasks[str(base[task_id]["capability_id"])].append(task_id)
    for name, ids in sorted(family_tasks.items()):
        family[name] = {
            "tasks": len(ids),
            "base_strict": round(statistics.fmean(metric(base[key], "strict_success") for key in ids), 6),
            "sft_strict": round(statistics.fmean(metric(sft[key], "strict_success") for key in ids), 6),
            "base_diagnostic": round(statistics.fmean(metric(base[key], "diagnostic") for key in ids), 6),
            "sft_diagnostic": round(statistics.fmean(metric(sft[key], "diagnostic") for key in ids), 6),
        }
    strict_bootstrap = paired_bootstrap(
        task_ids,
        lambda key: metric(sft[key], "strict_success") - metric(base[key], "strict_success"),
        seed=seed,
    )
    diagnostic_bootstrap = paired_bootstrap(
        task_ids,
        lambda key: metric(sft[key], "diagnostic") - metric(base[key], "diagnostic"),
        seed=seed + 1,
    )
    return {
        "schema_version": "studyhub.base-sft-development-comparison.v1",
        "status": "PASS" if not failures else "FAIL",
        "claim": "DIRECTIONAL_PAIRED_EVIDENCE_ONLY",
        "benchmark_manifest_sha256": base_summary.get("benchmark_manifest_sha256"),
        "sealed_used": False,
        "paired_tasks": len(task_ids),
        "base": {
            "run_id": base_summary.get("run_id"),
            "model": base_summary.get("model"),
            "strict_success_rate": base_summary.get("strict_success_rate"),
            "mean_diagnostic_score": base_summary.get("mean_score"),
            "mean_tool_calls": base_summary.get("tool_calls", {}).get("mean"),
            "mean_latency_seconds": base_summary.get("latency_seconds", {}).get("mean"),
            "episodes_sha256": sha256(base_path),
            "failures": dict(hard_gate_counts(base).most_common()),
        },
        "sft": {
            "run_id": sft_summary.get("run_id"),
            "model": sft_summary.get("model"),
            "strict_success_rate": sft_summary.get("strict_success_rate"),
            "mean_diagnostic_score": sft_summary.get("mean_score"),
            "mean_tool_calls": sft_summary.get("tool_calls", {}).get("mean"),
            "mean_latency_seconds": sft_summary.get("latency_seconds", {}).get("mean"),
            "episodes_sha256": sha256(sft_path),
            "failures": dict(hard_gate_counts(sft).most_common()),
        },
        "paired_strict": {
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "delta": strict_bootstrap,
        },
        "paired_diagnostic_delta": diagnostic_bootstrap,
        "mean_tool_validity_delta": round(
            statistics.fmean(
                metric(sft[key], "tool_validity") - metric(base[key], "tool_validity") for key in task_ids
            ),
            6,
        ),
        "mean_tool_calls_delta": round(
            statistics.fmean(metric(sft[key], "tool_calls") - metric(base[key], "tool_calls") for key in task_ids),
            6,
        ),
        "capabilities": family,
        "approx_independent_mde_80_power_pp": base_summary.get("approx_independent_mde_80_power_pp"),
        "limitations": [
            "51 Development tasks provide directional paired evidence, not a small-effect significance claim.",
            "No Sealed-A/B or external benchmark result is used in this comparison.",
        ],
        "failures": failures,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-run", type=Path, required=True)
    parser.add_argument("--sft-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260827)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = compare(args.base_run, args.sft_run, seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
