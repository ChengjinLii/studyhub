#!/usr/bin/env python3
"""Select the controlled 45k runtime-native SFT set from the v3 pool."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from studyhub_agent.trajectory.runtime_sft import stable_hash, validate_runtime_trajectory

FINAL_QUOTAS = {
    "toolace": 6_400,
    "hermes_function_calling": 2_600,
    "coig_exam": 4_500,
    "studyhub_2wiki_replay": 12_000,
    "studyhub_qasper_replay": 3_000,
    "studyhub_metadata_replay": 6_000,
    "studyhub_memory_replay": 4_000,
    "studyhub_acl_recovery": 4_000,
    "studyhub_web_fallback": 3_000,
    "studyhub_state_tools": 3_000,
}
SOURCE_GROUP_CAPS = {"studyhub_2wiki_replay": 1}

_SPACE = re.compile(r"\s+")
_CITATION = re.compile(r"\[(?:wiki|paper|studyhub-material|web-material):[^]]+]", re.IGNORECASE)
_OPAQUE_ID = re.compile(r"\b(?:call|memory|paid-source)_[A-Za-z0-9:_-]+\b|\b[0-9a-f]{12,}\b")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_text(value: str) -> str:
    return _SPACE.sub(" ", value).strip().casefold()


def near_signature(row: dict[str, Any]) -> str:
    user = next(
        (str(message.get("content", "")) for message in row["messages"] if message.get("role") == "user"),
        "",
    )
    final = next(
        (
            str(message.get("content", ""))
            for message in reversed(row["messages"])
            if message.get("role") == "assistant" and not message.get("tool_calls")
        ),
        "",
    )
    text = _CITATION.sub("[source]", f"{user}\n{final}")
    text = _OPAQUE_ID.sub("<id>", text)
    return hashlib.sha256(normalized_text(text).encode()).hexdigest()


def semantic_template(row: dict[str, Any]) -> str:
    user = next(
        (str(message.get("content", "")) for message in row["messages"] if message.get("role") == "user"),
        "",
    )
    user = re.sub(r"《[^》]+》|'[^']+'|\"[^\"]+\"", "<entity>", user)
    user = re.sub(r"\b\d+(?:\.\d+)?\b", "<number>", user)
    user = _OPAQUE_ID.sub("<id>", user)
    return hashlib.sha256(f"{row['task_family']}:{normalized_text(user)}".encode()).hexdigest()[:20]


def split_for(row: dict[str, Any]) -> str:
    if row.get("split_hint") in {"train", "validation", "protocol_holdout"}:
        return str(row["split_hint"])
    bucket = int(stable_hash(str(row["group_id"]), salt="runtime-sft-v3-split")[:8], 16) % 10_000
    if bucket < 9_000:
        return "train"
    if bucket < 9_500:
        return "validation"
    return "protocol_holdout"


def selection_rank(row: dict[str, Any]) -> tuple[int, str]:
    quality_order = {
        "expert_complete": 0,
        "oracle_derived_expert_complete": 0,
        "deterministic_fixture_complete": 0,
        "expert_action_synthetic_observation": 1,
        "expert_action_only": 2,
    }
    return (
        quality_order.get(str(row.get("quality_tier")), 1),
        stable_hash(str(row["id"]), salt="runtime-sft-v3-final-selection"),
    )


def split_quotas(total: int) -> dict[str, int]:
    validation = round(total * 0.05)
    protocol_holdout = round(total * 0.05)
    return {
        "train": total - validation - protocol_holdout,
        "validation": validation,
        "protocol_holdout": protocol_holdout,
    }


def select_diverse_rows(
    rows: list[dict[str, Any]],
    quota: int,
    *,
    max_rows_per_group: int | None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    group_counts: Counter[str] = Counter()
    for row in sorted(rows, key=selection_rank):
        group_id = str(row["group_id"])
        if max_rows_per_group is not None and group_counts[group_id] >= max_rows_per_group:
            continue
        selected.append(row)
        group_counts[group_id] += 1
        if len(selected) == quota:
            break
    return selected


def benchmark_prompt_hashes(project: Path, manifest: dict[str, Any]) -> tuple[set[str], int]:
    paths = [
        *sorted((project / "benchmarks/studyhub-agent-v2").glob("*/tasks.jsonl")),
        *sorted((project / "artifacts/benchmark-v2/studyhub-agent-v2/tasks").glob("*.jsonl")),
    ]
    hashes: set[str] = set()
    count = 0
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            prompt = next(
                (str(row.get(key, "")) for key in ("request", "user_request", "prompt", "goal") if row.get(key)),
                "",
            )
            if prompt:
                count += 1
                hashes.add(hashlib.sha256(normalized_text(prompt).encode()).hexdigest())
    expected = sum(int(value) for value in manifest.get("counts", {}).values())
    if count != expected or len(hashes) != expected:
        raise RuntimeError(
            "frozen benchmark prompt inventory is incomplete or duplicated: "
            f"rows={count}, unique={len(hashes)}, expected={expected}"
        )
    return hashes, count


def public_benchmark_prompt_hashes(project: Path, manifest: dict[str, Any]) -> tuple[set[str], int]:
    """Hash only public Benchmark v2 prompts without opening sealed task files."""
    hashes: set[str] = set()
    count = 0
    for relative in sorted(manifest["public_files"]):
        if not relative.endswith("tasks.jsonl"):
            continue
        path = project / "benchmarks/studyhub-agent-v2" / relative
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            prompt = next(
                (str(row.get(key, "")) for key in ("request", "user_request", "prompt", "goal") if row.get(key)),
                "",
            )
            if prompt:
                count += 1
                hashes.add(hashlib.sha256(normalized_text(prompt).encode()).hexdigest())
    expected = sum(
        int(manifest["counts"][split])
        for split in ("regression", "development", "calibration_challenge")
    )
    if count != expected or len(hashes) != expected:
        raise RuntimeError(f"public benchmark prompt inventory mismatch: rows={count}, unique={len(hashes)}, expected={expected}")
    return hashes, count


def candidate_prompt_hash(row: dict[str, Any]) -> str:
    prompt = next(
        (str(message.get("content", "")) for message in row["messages"] if message.get("role") == "user"),
        "",
    )
    return hashlib.sha256(normalized_text(prompt).encode()).hexdigest()


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=project / "datasets/interim/runtime_sft_v3/candidates.jsonl")
    parser.add_argument("--output", type=Path, default=project / "datasets/interim/runtime_sft_v3/selected.jsonl")
    parser.add_argument("--quota-scale", type=float, default=1.0, help="Scale final quotas for smoke tests.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0 < args.quota_scale <= 1:
        raise ValueError("--quota-scale must be in (0, 1]")
    project = Path(__file__).resolve().parents[2]
    quotas = {source: max(1, round(count * args.quota_scale)) for source, count in FINAL_QUOTAS.items()}
    benchmark_manifest_path = project / "benchmarks/studyhub-agent-v2/manifest.json"
    benchmark_manifest = json.loads(benchmark_manifest_path.read_text(encoding="utf-8"))
    if benchmark_manifest.get("benchmark_version") != "studyhub-agentbench-v2":
        raise RuntimeError("runtime SFT must be isolated from StudyHub AgentBench v2")
    if benchmark_manifest.get("benchmark_revision") != "2.0.0":
        raise RuntimeError(f"unexpected benchmark revision: {benchmark_manifest.get('benchmark_revision')}")
    if benchmark_manifest.get("status") != "FROZEN_FOR_BASELINE":
        raise RuntimeError("benchmark manifest is not frozen")
    candidate_manifest_path = args.input.with_suffix(".manifest.json")
    candidate_manifest = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
    expected_lock = {
        "benchmark_version": benchmark_manifest["benchmark_version"],
        "benchmark_revision": benchmark_manifest["benchmark_revision"],
        "benchmark_status": benchmark_manifest["status"],
        "benchmark_tasks": sum(int(value) for value in benchmark_manifest["counts"].values()),
        "benchmark_manifest_sha256": sha256(benchmark_manifest_path),
        "benchmark_source_inventory_sha256": benchmark_manifest["hidden_files"]["source-inventory.jsonl"],
    }
    if candidate_manifest.get("benchmark_lock") != expected_lock:
        raise RuntimeError("candidate pool is not bound to the current frozen Benchmark v2 manifest")
    pools: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ids: set[str] = set()
    content_hashes: set[str] = set()
    near_hashes: set[tuple[str, str]] = set()
    drops: Counter[str] = Counter()
    benchmark_hashes, benchmark_task_count = benchmark_prompt_hashes(project, benchmark_manifest)
    benchmark_prompt_overlap: list[str] = []
    with args.input.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            source = str(row.get("source_dataset"))
            if source not in quotas:
                drops["unknown_source"] += 1
                continue
            failures = validate_runtime_trajectory(row)
            if failures:
                drops["runtime_contract"] += 1
                continue
            if row["id"] in ids:
                drops["duplicate_id"] += 1
                continue
            ids.add(row["id"])
            if row["content_sha256"] in content_hashes:
                drops["exact_duplicate"] += 1
                continue
            content_hashes.add(row["content_sha256"])
            signature = near_signature(row)
            near_key = (source, signature)
            if near_key in near_hashes:
                drops["near_duplicate"] += 1
                continue
            near_hashes.add(near_key)
            if candidate_prompt_hash(row) in benchmark_hashes:
                benchmark_prompt_overlap.append(str(row["id"]))
                drops["benchmark_prompt_overlap"] += 1
                continue
            row["split"] = split_for(row)
            row["semantic_template_cluster"] = semantic_template(row)
            pools[source].append(row)

    selected: list[dict[str, Any]] = []
    candidate_counts = {source: len(rows) for source, rows in pools.items()}
    requested_source_split_quotas: dict[str, dict[str, int]] = {}
    for source, quota in quotas.items():
        rows_by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in pools[source]:
            rows_by_split[str(row["split"])].append(row)
        source_split_quotas = split_quotas(quota)
        requested_source_split_quotas[source] = source_split_quotas
        for split, split_quota in source_split_quotas.items():
            rows = select_diverse_rows(
                rows_by_split[split],
                split_quota,
                max_rows_per_group=SOURCE_GROUP_CAPS.get(source),
            )
            if len(rows) < split_quota:
                raise RuntimeError(f"insufficient selected pool for {source}/{split}: {len(rows)}/{split_quota}")
            selected.extend(rows)
    selected.sort(key=lambda row: stable_hash(str(row["id"]), salt=f"runtime-sft-v3:{row['split']}"))

    split_groups: dict[str, set[str]] = defaultdict(set)
    split_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    source_split_counts: dict[str, Counter[str]] = defaultdict(Counter)
    source_group_counts: Counter[tuple[str, str]] = Counter()
    capability_counts: Counter[str] = Counter()
    semantic_counts: Counter[str] = Counter()
    runtime_native_count = 0
    complete_count = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as stream:
        for row in selected:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            split = row["split"]
            source = row["source_dataset"]
            split_counts[split] += 1
            split_groups[split].add(str(row["group_id"]))
            source_counts[source] += 1
            source_split_counts[source][split] += 1
            source_group_counts[(source, str(row["group_id"]))] += 1
            capability_counts.update(row.get("capability_tags", []))
            semantic_counts[f"{source}:{row['semantic_template_cluster']}"] += 1
            runtime_native_count += int(row["runtime_native"])
            complete_count += int(row["trajectory_status"] == "complete")
    overlap = {
        "train_validation": len(split_groups["train"] & split_groups["validation"]),
        "train_protocol_holdout": len(split_groups["train"] & split_groups["protocol_holdout"]),
        "validation_protocol_holdout": len(split_groups["validation"] & split_groups["protocol_holdout"]),
    }
    if any(overlap.values()):
        raise RuntimeError(f"group leakage detected after selection: {overlap}")
    total = len(selected)
    studyhub_custom = sum(
        count
        for source, count in source_counts.items()
        if source
        in {
            "studyhub_metadata_replay",
            "studyhub_memory_replay",
            "studyhub_acl_recovery",
            "studyhub_web_fallback",
            "studyhub_state_tools",
        }
    )
    manifest = {
        "schema_version": "studyhub.runtime-sft-selected-manifest.v3",
        "status": "SELECTED_PENDING_TOKENIZATION",
        "total": total,
        "quotas": quotas,
        "requested_source_split_quotas": requested_source_split_quotas,
        "candidate_counts_after_quality_filter": candidate_counts,
        "source_counts": dict(sorted(source_counts.items())),
        "source_split_counts": {
            source: dict(sorted(counts.items())) for source, counts in sorted(source_split_counts.items())
        },
        "source_group_caps": SOURCE_GROUP_CAPS,
        "max_group_rows_by_source": {
            source: max(
                (
                    count
                    for (candidate_source, _group), count in source_group_counts.items()
                    if candidate_source == source
                ),
                default=0,
            )
            for source in sorted(source_counts)
        },
        "split_counts": dict(sorted(split_counts.items())),
        "split_ratios": {key: round(value / total, 6) for key, value in sorted(split_counts.items())},
        "group_overlap": overlap,
        "runtime_native_count": runtime_native_count,
        "runtime_native_share": round(runtime_native_count / total, 6),
        "complete_count": complete_count,
        "studyhub_custom_count": studyhub_custom,
        "studyhub_custom_share": round(studyhub_custom / total, 6),
        "capability_counts": dict(sorted(capability_counts.items())),
        "quality_filter_drops": dict(sorted(drops.items())),
        "semantic_template_clusters": len(semantic_counts),
        "largest_semantic_template_cluster": max(semantic_counts.values(), default=0),
        "largest_semantic_template_cluster_share": round(max(semantic_counts.values(), default=0) / total, 6),
        "benchmark_tasks_hashed": benchmark_task_count,
        "benchmark_prompt_overlap_count": len(benchmark_prompt_overlap),
        "benchmark_prompt_overlap_ids": benchmark_prompt_overlap,
        "benchmark_lock": expected_lock,
        "input_sha256": sha256(args.input),
        "candidate_manifest_sha256": sha256(candidate_manifest_path),
        "output_sha256": sha256(args.output),
    }
    args.output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
