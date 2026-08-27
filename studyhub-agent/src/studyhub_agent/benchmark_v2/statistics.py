from __future__ import annotations

import random
import statistics
from collections import defaultdict
from collections.abc import Callable
from typing import Any


def cluster_bootstrap_interval(
    rows: list[dict[str, Any]],
    *,
    value: Callable[[dict[str, Any]], float],
    cluster: Callable[[dict[str, Any]], str],
    seed: int,
    samples: int = 5000,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[cluster(row)].append(row)
    keys = sorted(grouped)
    if not keys:
        return {"point": 0.0, "ci95": [0.0, 0.0], "effective_clusters": 0, "tasks": 0}
    point = statistics.fmean(value(row) for row in rows)
    rng = random.Random(seed)
    estimates = []
    for _ in range(samples):
        sampled = [rng.choice(keys) for _ in keys]
        sample_rows = [row for key in sampled for row in grouped[key]]
        estimates.append(statistics.fmean(value(row) for row in sample_rows))
    estimates.sort()
    return {
        "point": round(point, 6),
        "ci95": [round(estimates[int(samples * 0.025)], 6), round(estimates[int(samples * 0.975)], 6)],
        "effective_clusters": len(keys),
        "tasks": len(rows),
    }


def paired_cluster_bootstrap(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    *,
    value: Callable[[dict[str, Any]], float],
    task_id: Callable[[dict[str, Any]], str],
    cluster: Callable[[dict[str, Any]], str],
    seed: int,
    samples: int = 5000,
) -> dict[str, Any]:
    left_by_id = {task_id(row): row for row in left}
    right_by_id = {task_id(row): row for row in right}
    common = sorted(set(left_by_id) & set(right_by_id))
    grouped: dict[str, list[str]] = defaultdict(list)
    for key in common:
        grouped[cluster(left_by_id[key])].append(key)
    clusters = sorted(grouped)
    if not clusters:
        return {"delta": 0.0, "ci95": [0.0, 0.0], "effective_clusters": 0, "paired_tasks": 0}
    deltas = {key: value(right_by_id[key]) - value(left_by_id[key]) for key in common}
    point = statistics.fmean(deltas.values())
    rng = random.Random(seed)
    estimates = []
    for _ in range(samples):
        selected = [rng.choice(clusters) for _ in clusters]
        keys = [key for name in selected for key in grouped[name]]
        estimates.append(statistics.fmean(deltas[key] for key in keys))
    estimates.sort()
    return {
        "delta": round(point, 6),
        "ci95": [round(estimates[int(samples * 0.025)], 6), round(estimates[int(samples * 0.975)], 6)],
        "effective_clusters": len(clusters),
        "paired_tasks": len(common),
    }
