"""Paired statistics and multi-seed summaries for controlled-v2 evaluations."""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..spec import load_jsonl


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _metric_map(rows: Sequence[Mapping[str, Any]], metric: str) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for row in rows:
        example_id = str(row["example_id"])
        value = row.get("scores", {}).get(metric)
        if value is None:
            continue
        if example_id in result:
            raise ValueError(f"duplicate prediction example_id: {example_id}")
        result[example_id] = bool(value)
    return result


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("quantile requires non-empty values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def paired_bootstrap(
    baseline: Sequence[bool],
    candidate: Sequence[bool],
    *,
    resamples: int = 10_000,
    seed: int = 20260812,
) -> dict[str, Any]:
    if len(baseline) != len(candidate) or not baseline:
        raise ValueError("paired bootstrap requires equal non-empty samples")
    rng = random.Random(seed)
    size = len(baseline)
    observed = sum(candidate) / size - sum(baseline) / size
    deltas: list[float] = []
    for _ in range(resamples):
        indices = [rng.randrange(size) for _ in range(size)]
        candidate_rate = sum(candidate[index] for index in indices) / size
        baseline_rate = sum(baseline[index] for index in indices) / size
        deltas.append(candidate_rate - baseline_rate)
    return {
        "resamples": resamples,
        "seed": seed,
        "records": size,
        "observed_delta": round(observed, 6),
        "ci95": [
            round(_quantile(deltas, 0.025), 6),
            round(_quantile(deltas, 0.975), 6),
        ],
        "probability_candidate_better": round(
            sum(delta > 0 for delta in deltas) / resamples, 6
        ),
    }


def mcnemar_exact(
    baseline: Sequence[bool], candidate: Sequence[bool]
) -> dict[str, Any]:
    if len(baseline) != len(candidate) or not baseline:
        raise ValueError("McNemar requires equal non-empty samples")
    baseline_only = sum(a and not b for a, b in zip(baseline, candidate, strict=True))
    candidate_only = sum(not a and b for a, b in zip(baseline, candidate, strict=True))
    discordant = baseline_only + candidate_only
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(
            math.comb(discordant, value)
            for value in range(min(baseline_only, candidate_only) + 1)
        ) / (2**discordant)
        p_value = min(1.0, 2 * tail)
    return {
        "baseline_pass_candidate_fail": baseline_only,
        "baseline_fail_candidate_pass": candidate_only,
        "discordant_pairs": discordant,
        "exact_two_sided_p": round(p_value, 10),
    }


def compare_prediction_files(
    *,
    baseline_path: Path,
    candidate_path: Path,
    metric: str,
    resamples: int = 10_000,
    seed: int = 20260812,
) -> dict[str, Any]:
    baseline_map = _metric_map(load_jsonl(baseline_path), metric)
    candidate_map = _metric_map(load_jsonl(candidate_path), metric)
    if set(baseline_map) != set(candidate_map):
        missing_baseline = sorted(set(candidate_map) - set(baseline_map))
        missing_candidate = sorted(set(baseline_map) - set(candidate_map))
        raise ValueError(
            "paired prediction IDs differ: "
            f"missing baseline={missing_baseline[:5]}, "
            f"missing candidate={missing_candidate[:5]}"
        )
    ids = sorted(baseline_map)
    baseline = [baseline_map[item] for item in ids]
    candidate = [candidate_map[item] for item in ids]
    return {
        "schema_version": "studyhub.agent.sft.controlled_v2.paired_stats.v1",
        "metric": metric,
        "baseline_path": str(baseline_path),
        "candidate_path": str(candidate_path),
        "baseline_rate": round(sum(baseline) / len(baseline), 6),
        "candidate_rate": round(sum(candidate) / len(candidate), 6),
        "paired_bootstrap": paired_bootstrap(
            baseline, candidate, resamples=resamples, seed=seed
        ),
        "mcnemar_exact": mcnemar_exact(baseline, candidate),
    }


def summarize_seeds(
    summaries: Sequence[Mapping[str, Any]],
    *,
    metric: str,
    expected_seeds: Sequence[int],
) -> dict[str, Any]:
    values: list[tuple[int, float]] = []
    for summary in summaries:
        seed = int(summary["seed"])
        raw_value = summary["metrics"][metric]["rate"]
        if raw_value is None:
            raise ValueError(f"metric {metric} has no denominator for seed {seed}")
        values.append((seed, float(raw_value)))
    values.sort()
    if [seed for seed, _ in values] != sorted(expected_seeds):
        raise ValueError(
            f"seed set mismatch: found {[seed for seed, _ in values]}, "
            f"expected {sorted(expected_seeds)}"
        )
    rates = [value for _, value in values]
    return {
        "metric": metric,
        "seeds": [{"seed": seed, "rate": rate} for seed, rate in values],
        "mean": round(statistics.fmean(rates), 6),
        "std": round(statistics.stdev(rates), 6) if len(rates) > 1 else 0.0,
        "min": min(rates),
        "max": max(rates),
        "median_seed": min(
            values, key=lambda item: abs(item[1] - statistics.median(rates))
        )[0],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--metric", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resamples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260812)
    args = parser.parse_args()
    result = compare_prediction_files(
        baseline_path=args.baseline,
        candidate_path=args.candidate,
        metric=args.metric,
        resamples=args.resamples,
        seed=args.seed,
    )
    _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
