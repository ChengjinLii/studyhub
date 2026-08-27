#!/usr/bin/env python3
"""Build an immutable-v3-preserving runtime-SFT-v3.1 teacher candidate."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for entry in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts.data.select_runtime_sft_v3 import (
    candidate_prompt_hash,
    near_signature,
    public_benchmark_prompt_hashes,
    semantic_template,
    sha256,
    split_for,
)
from studyhub_agent.trajectory.runtime_sft import stable_hash, validate_runtime_trajectory

CUSTOM_SOURCES = {
    "studyhub_metadata_replay",
    "studyhub_memory_replay",
    "studyhub_acl_recovery",
    "studyhub_web_fallback",
    "studyhub_state_tools",
    "studyhub_teacher_v1",
}
COMPLETE_QUALITY_ORDER = {
    "teacher_verified_complete": 0,
    "teacher_repaired_complete": 1,
    "expert_recorded_complete": 2,
    "expert_complete": 2,
    "oracle_verified_complete": 3,
    "oracle_derived_expert_complete": 3,
    "deterministic_fixture_complete": 4,
}
SPLITS = ("train", "validation", "protocol_holdout")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _quality_rank(row: dict[str, Any]) -> tuple[int, str]:
    return (
        COMPLETE_QUALITY_ORDER.get(str(row.get("quality_tier")), 99),
        stable_hash(str(row.get("id")), salt="runtime-sft-v3.1-quality"),
    )


def _select_teacher_rows(
    accepted: list[dict[str, Any]],
    *,
    base_content: set[str],
    base_near: set[tuple[str, str]],
    public_benchmark_hashes: set[str],
    max_rows_per_group: int,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    selected: list[dict[str, Any]] = []
    drops: Counter[str] = Counter()
    groups: Counter[str] = Counter()
    contents = set(base_content)
    near = set(base_near)
    for row in sorted(accepted, key=_quality_rank):
        failures = validate_runtime_trajectory(row)
        if failures:
            drops["runtime_contract"] += 1
            continue
        if row.get("quality_tier") not in {"teacher_verified_complete", "teacher_repaired_complete"}:
            drops["not_teacher_verified"] += 1
            continue
        if row.get("trajectory_status") != "complete":
            drops["not_complete"] += 1
            continue
        is_verified_direct = row.get("task_family") == "direct_abstention"
        if not row.get("runtime_native") and not is_verified_direct:
            drops["not_runtime_native"] += 1
            continue
        if candidate_prompt_hash(row) in public_benchmark_hashes:
            drops["public_benchmark_prompt_overlap"] += 1
            continue
        group = str(row["group_id"])
        if groups[group] >= max_rows_per_group:
            drops["teacher_group_cap"] += 1
            continue
        content = str(row["content_sha256"])
        signature = (str(row["source_dataset"]), near_signature(row))
        if content in contents:
            drops["exact_duplicate"] += 1
            continue
        if signature in near:
            drops["near_duplicate"] += 1
            continue
        prepared = dict(row)
        prepared["split"] = "train"
        prepared["semantic_template_cluster"] = semantic_template(prepared)
        selected.append(prepared)
        groups[group] += 1
        contents.add(content)
        near.add(signature)
    return selected, drops


def _action_removals(
    base: list[dict[str, Any]],
    *,
    replacement_count: int,
    teacher_count: int,
) -> list[dict[str, Any]]:
    action_rows = [row for row in base if row.get("trajectory_status") == "action_only"]
    group_sizes = Counter(str(row["group_id"]) for row in action_rows)
    ordered = sorted(
        action_rows,
        key=lambda row: (
            0 if row.get("source_dataset") == "toolace" else 1,
            -group_sizes[str(row["group_id"])],
            stable_hash(str(row["id"]), salt="runtime-sft-v3.1-action-removal"),
        ),
    )
    train = [row for row in ordered if row.get("split") == "train"]
    if len(train) < teacher_count:
        raise RuntimeError(f"not enough train action-only rows for teacher replacement: {len(train)}/{teacher_count}")
    selected_ids = {str(row["id"]) for row in train[:teacher_count]}
    for row in ordered:
        if len(selected_ids) >= replacement_count:
            break
        selected_ids.add(str(row["id"]))
    if len(selected_ids) != replacement_count:
        raise RuntimeError(f"not enough action-only rows: {len(selected_ids)}/{replacement_count}")
    return [row for row in base if str(row["id"]) in selected_ids]


def _candidate_pool(
    path: Path,
    *,
    excluded_ids: set[str],
    public_benchmark_hashes: set[str],
    group_split: dict[str, str],
) -> tuple[dict[tuple[str, str], deque[dict[str, Any]]], Counter[str]]:
    rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    drops: Counter[str] = Counter()
    limits = {"train": 1_200, "validation": 180, "protocol_holdout": 180}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            source = str(row.get("source_dataset", ""))
            split = split_for(row)
            key = (source, split)
            if len(rows[key]) >= limits[split]:
                continue
            if str(row.get("id")) in excluded_ids:
                continue
            if row.get("trajectory_status") != "complete":
                continue
            if str(row.get("quality_tier")) not in COMPLETE_QUALITY_ORDER:
                continue
            if validate_runtime_trajectory(row):
                drops["runtime_contract"] += 1
                continue
            if candidate_prompt_hash(row) in public_benchmark_hashes:
                drops["public_benchmark_prompt_overlap"] += 1
                continue
            group = str(row["group_id"])
            if group in group_split and group_split[group] != split:
                drops["group_split_conflict"] += 1
                continue
            prepared = dict(row)
            prepared["split"] = split
            prepared["semantic_template_cluster"] = semantic_template(prepared)
            rows[key].append(prepared)
    return {
        key: deque(sorted(values, key=_quality_rank))
        for key, values in rows.items()
    }, drops


def _fill_complete_replacements(
    pools: dict[tuple[str, str], deque[dict[str, Any]]],
    *,
    required_by_split: Counter[str],
    base_counts: Counter[str],
    total: int,
    ids: set[str],
    contents: set[str],
    near: set[tuple[str, str]],
    group_split: dict[str, str],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    selected: list[dict[str, Any]] = []
    drops: Counter[str] = Counter()
    counts = Counter(base_counts)
    for split in SPLITS:
        while sum(row["split"] == split for row in selected) < required_by_split[split]:
            sources = sorted(
                {source for source, candidate_split in pools if candidate_split == split and pools[(source, split)]},
                key=lambda source: (counts[source] / max(total, 1), source),
            )
            if not sources:
                raise RuntimeError(f"insufficient complete backfill candidates for {split}")
            added = False
            for source in sources:
                cap_fraction = 0.15 if source in CUSTOM_SOURCES else 0.25
                if counts[source] >= math.floor(total * cap_fraction):
                    drops["source_share_cap"] += 1
                    pools[(source, split)].clear()
                    continue
                pool = pools[(source, split)]
                while pool:
                    row = pool.popleft()
                    row_id = str(row["id"])
                    content = str(row["content_sha256"])
                    signature = (source, near_signature(row))
                    group = str(row["group_id"])
                    if row_id in ids:
                        drops["duplicate_id"] += 1
                        continue
                    if content in contents:
                        drops["exact_duplicate"] += 1
                        continue
                    if signature in near:
                        drops["near_duplicate"] += 1
                        continue
                    if group in group_split and group_split[group] != split:
                        drops["group_split_conflict"] += 1
                        continue
                    selected.append(row)
                    ids.add(row_id)
                    contents.add(content)
                    near.add(signature)
                    group_split[group] = split
                    counts[source] += 1
                    added = True
                    break
                if added:
                    break
            if not added and not any(pools[(source, split)] for source in sources):
                raise RuntimeError(f"all complete backfill candidates were rejected for {split}")
    return selected, drops


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=PROJECT_ROOT / "datasets/interim/runtime_sft_v3/selected.jsonl")
    parser.add_argument(
        "--candidate-pool",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/runtime_sft_v3/candidates.jsonl",
    )
    parser.add_argument(
        "--teacher",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/studyhub_teacher_v1/accepted.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/runtime_sft_v3_1/selected.jsonl",
    )
    parser.add_argument("--teacher-group-cap", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.teacher_group_cap < 1:
        raise ValueError("--teacher-group-cap must be positive")
    authorization = json.loads(
        (PROJECT_ROOT / "configs/program-v3/overnight-sft-baseline-authorization.json").read_text(encoding="utf-8")
    )
    expected_base_sha = authorization["lineage"]["selected_jsonl_sha256"]
    if sha256(args.base) != expected_base_sha:
        raise RuntimeError("immutable runtime-SFT-v3.0 selected hash drift")
    benchmark_path = PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    public_hashes, public_tasks = public_benchmark_prompt_hashes(PROJECT_ROOT, benchmark)
    base = _read_jsonl(args.base)
    accepted = _read_jsonl(args.teacher)
    base_content = {str(row["content_sha256"]) for row in base}
    base_near = {(str(row["source_dataset"]), near_signature(row)) for row in base}
    teacher, teacher_drops = _select_teacher_rows(
        accepted,
        base_content=base_content,
        base_near=base_near,
        public_benchmark_hashes=public_hashes,
        max_rows_per_group=args.teacher_group_cap,
    )
    total = len(base)
    action_count = sum(row.get("trajectory_status") == "action_only" for row in base)
    minimum_replacements = max(0, action_count - math.floor(total * 0.05))
    replacement_count = max(minimum_replacements, len(teacher))
    removals = _action_removals(base, replacement_count=replacement_count, teacher_count=len(teacher))
    removal_ids = {str(row["id"]) for row in removals}
    kept = [row for row in base if str(row["id"]) not in removal_ids]
    removed_by_split = Counter(str(row["split"]) for row in removals)
    teacher_by_split = Counter(str(row["split"]) for row in teacher)
    filler_required = Counter({split: removed_by_split[split] - teacher_by_split[split] for split in SPLITS})

    current = [*kept, *teacher]
    ids = {str(row["id"]) for row in current}
    contents = {str(row["content_sha256"]) for row in current}
    near = {(str(row["source_dataset"]), near_signature(row)) for row in current}
    group_split: dict[str, str] = {}
    for row in current:
        group = str(row["group_id"])
        split = str(row["split"])
        if group in group_split and group_split[group] != split:
            raise RuntimeError(f"pre-existing group split conflict: {group}")
        group_split[group] = split
    pools, pool_drops = _candidate_pool(
        args.candidate_pool,
        excluded_ids={str(row["id"]) for row in base},
        public_benchmark_hashes=public_hashes,
        group_split=group_split,
    )
    source_counts = Counter(str(row["source_dataset"]) for row in current)
    filler, filler_drops = _fill_complete_replacements(
        pools,
        required_by_split=filler_required,
        base_counts=source_counts,
        total=total,
        ids=ids,
        contents=contents,
        near=near,
        group_split=group_split,
    )
    result = [*current, *filler]
    result.sort(key=lambda row: (SPLITS.index(str(row["split"])), stable_hash(str(row["id"]), salt="runtime-sft-v3.1")))
    if len(result) != total:
        raise RuntimeError(f"v3.1 candidate must preserve row count: {len(result)}/{total}")
    _write_jsonl(args.output, result)

    split_groups: dict[str, set[str]] = defaultdict(set)
    split_counts: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    quality: Counter[str] = Counter()
    action_only = 0
    benchmark_overlap = 0
    for row in result:
        split = str(row["split"])
        split_counts[split] += 1
        split_groups[split].add(str(row["group_id"]))
        sources[str(row["source_dataset"])] += 1
        quality[str(row["quality_tier"])] += 1
        action_only += int(row.get("trajectory_status") == "action_only")
        benchmark_overlap += int(candidate_prompt_hash(row) in public_hashes)
    overlap = {
        "train_validation": len(split_groups["train"] & split_groups["validation"]),
        "train_protocol_holdout": len(split_groups["train"] & split_groups["protocol_holdout"]),
        "validation_protocol_holdout": len(split_groups["validation"] & split_groups["protocol_holdout"]),
    }
    constraints = {
        "rows_45k_to_50k": 45_000 <= len(result) <= 50_000,
        "action_only_at_most_5_percent": action_only / len(result) <= 0.05,
        "single_source_at_most_25_percent": max(sources.values()) / len(result) <= 0.25,
        "custom_source_at_most_15_percent": all(
            count / len(result) <= 0.15 for source, count in sources.items() if source in CUSTOM_SOURCES
        ),
        "group_split_overlap_zero": not any(overlap.values()),
        "public_benchmark_prompt_overlap_zero": benchmark_overlap == 0,
    }
    enough_teacher = len(teacher) >= 500
    status = (
        "CANDIDATE_READY_FOR_AUDIT"
        if enough_teacher and all(constraints.values())
        else "CANDIDATE_INSUFFICIENT_TEACHER_VOLUME"
        if not enough_teacher
        else "CANDIDATE_CONSTRAINT_FAILURE"
    )
    manifest = {
        "schema_version": "studyhub.runtime-sft-v3.1-candidate-manifest.v1",
        "status": status,
        "formal_release": False,
        "base_release": "runtime-SFT-v3.0",
        "base_rows": len(base),
        "base_sha256": sha256(args.base),
        "candidate_rows": len(result),
        "candidate_sha256": sha256(args.output),
        "teacher_raw_accepted": len(accepted),
        "teacher_selected": len(teacher),
        "teacher_minimum_useful_target_met": enough_teacher,
        "teacher_group_cap": args.teacher_group_cap,
        "teacher_selection_drops": dict(teacher_drops.most_common()),
        "action_only_before": action_count,
        "action_only_after": action_only,
        "action_only_share_after": round(action_only / len(result), 6),
        "removed_action_only": len(removals),
        "complete_backfill": len(filler),
        "removed_by_split": dict(sorted(removed_by_split.items())),
        "filler_required_by_split": dict(sorted(filler_required.items())),
        "candidate_pool_drops": dict(pool_drops.most_common()),
        "filler_drops": dict(filler_drops.most_common()),
        "source_counts": dict(sorted(sources.items())),
        "source_shares": {source: round(count / len(result), 6) for source, count in sorted(sources.items())},
        "quality_tiers": dict(sorted(quality.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "group_overlap": overlap,
        "public_benchmark_tasks_checked": public_tasks,
        "public_benchmark_prompt_overlap": benchmark_overlap,
        "sealed_task_files_read": False,
        "sealed_overlap_recheck": "INHERITED_FROM_FROZEN_V3_SOURCE_LOCK_NOT_RECOMPUTED",
        "constraints": constraints,
        "candidate_pool_sha256": sha256(args.candidate_pool),
        "teacher_accepted_sha256": sha256(args.teacher) if args.teacher.is_file() else None,
        "benchmark_manifest_sha256": sha256(benchmark_path),
    }
    _write_json(args.output.with_suffix(".manifest.json"), manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if all(constraints.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
