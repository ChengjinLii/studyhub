#!/usr/bin/env python3
"""Build the isolated 16k Reward-v3 task candidate pool.

The builder reuses only parsers from the earlier open-data pipeline. It emits a
new public-task contract, training-only environments, path-agnostic hidden
verifiers and audit-only solvability witnesses.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import itertools
import json
import shutil
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from scripts.data import build_open_rl_tasks as open_v2  # noqa: E402
from training.rl.dataset_v3 import DATASET_SCHEMA_VERSION, FAMILY_MIX  # noqa: E402
from training.rl.task_factory_v3 import (  # noqa: E402
    CUSTOM_FACTORIES,
    convert_coig_candidate,
    convert_function_candidate,
    convert_search_candidate,
    stable_digest,
)

BASE_EXTERNAL = {
    "function_calling": 1280,
    "rag_and_multihop": 2000,
    "cross_tool": 1440,
    "long_horizon_and_deep_research": 800,
    "direct_answer_and_abstention": 880,
}
BASE_CUSTOM = {
    "function_calling": 640,
    "rag_and_multihop": 880,
    "web": 1920,
    "memory": 1920,
    "cross_tool": 1120,
    "recovery_and_acl": 1920,
    "long_horizon_and_deep_research": 800,
    "direct_answer_and_abstention": 400,
}
DEFAULT_CANDIDATES = 16000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def scaled_counts(base: dict[str, int], target: int) -> dict[str, int]:
    if target < 0:
        raise ValueError("target must be non-negative")
    total = sum(base.values())
    raw = {key: target * value / total for key, value in base.items()}
    result = {key: int(value) for key, value in raw.items()}
    remainder = target - sum(result.values())
    order = sorted(base, key=lambda key: (-(raw[key] - result[key]), key))
    for key in order[:remainder]:
        result[key] += 1
    return result


def allocation(candidate_count: int) -> tuple[dict[str, int], dict[str, int]]:
    custom_total = round(candidate_count * 0.60)
    external_total = candidate_count - custom_total
    return scaled_counts(BASE_EXTERNAL, external_total), scaled_counts(BASE_CUSTOM, custom_total)


def load_runtime_sft_exclusions(path: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    ids: dict[str, set[str]] = defaultdict(set)
    groups: dict[str, set[str]] = defaultdict(set)
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            source = str(row["source_dataset"])
            source_id = str(row.get("source_id", ""))
            group_id = str(row.get("group_id", source_id))
            if source in {"toolace", "hermes_function_calling", "coig_exam"}:
                ids[source].add(source_id)
                groups[source].add(group_id)
            elif source == "studyhub_2wiki_replay":
                ids["2wiki"].add(source_id)
                groups["2wiki"].add(group_id.removeprefix("2wiki-component:"))
            elif source == "studyhub_qasper_replay":
                ids["qasper"].add(source_id)
                groups["qasper"].add(group_id.removeprefix("qasper:"))
    return ids, groups


def _heap_select(
    rows: Iterable[dict[str, Any]],
    count: int,
    *,
    salt: str,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
    allow_shortfall: bool = False,
) -> list[dict[str, Any]]:
    if count == 0:
        return []
    heap: list[tuple[int, str, dict[str, Any]]] = []
    seen_groups: set[str] = set()
    seen_goals: set[str] = set()
    for row in rows:
        if predicate is not None and not predicate(row):
            continue
        group = f"{row['source_dataset']}:{row['group_id']}"
        goal_hash = stable_digest(str(row["user_request"]).casefold(), salt="goal")
        if group in seen_groups or goal_hash in seen_goals:
            continue
        key = int(stable_digest(str(row["task_id"]), salt=salt), 16)
        item = (-key, str(row["task_id"]), row)
        if len(heap) < count:
            heapq.heappush(heap, item)
            seen_groups.add(group)
            seen_goals.add(goal_hash)
            continue
        if item <= heap[0]:
            continue
        removed = heapq.heapreplace(heap, item)[2]
        seen_groups.discard(f"{removed['source_dataset']}:{removed['group_id']}")
        seen_goals.discard(stable_digest(str(removed["user_request"]).casefold(), salt="goal"))
        seen_groups.add(group)
        seen_goals.add(goal_hash)
    if len(heap) < count and not allow_shortfall:
        raise RuntimeError(f"only {len(heap)} candidates available for {salt}; need {count}")
    return [row for _, _, row in sorted(heap, key=lambda item: (-item[0], item[1]))]


def _function_candidates(
    raw_root: Path,
    excluded_ids: dict[str, set[str]],
) -> Iterator[dict[str, Any]]:
    yield from open_v2.iter_toolace(raw_root, excluded_ids["toolace"])
    yield from open_v2.iter_hermes(raw_root, excluded_ids["hermes_function_calling"])


def build_external(
    *,
    raw_root: Path,
    runtime_sft: Path,
    counts: dict[str, int],
) -> list[dict[str, Any]]:
    excluded_ids, excluded_groups = load_runtime_sft_exclusions(runtime_sft)
    function_rows = list(_function_candidates(raw_root, excluded_ids))
    function_selected = _heap_select(
        function_rows,
        counts.get("function_calling", 0),
        salt="v3-function",
        predicate=lambda row: len(row["verifier"].get("expected_calls", [])) <= 1,
    )
    cross_selected = _heap_select(
        function_rows,
        counts.get("cross_tool", 0),
        salt="v3-cross-function",
        predicate=lambda row: len(row["verifier"].get("expected_calls", [])) >= 2,
    )

    long_target = counts.get("long_horizon_and_deep_research", 0)
    qasper_target = min(long_target // 2, 400 if DEFAULT_CANDIDATES == 16000 else long_target // 2)
    qasper_rows = _heap_select(
        open_v2.iter_qasper(raw_root, excluded_groups["qasper"]),
        qasper_target,
        salt="v3-qasper-long",
        allow_shortfall=True,
    )
    wiki_long_target = long_target - len(qasper_rows)
    wiki_rows = open_v2.iter_2wiki(raw_root, excluded_ids["2wiki"])
    wiki_selected = _heap_select(
        wiki_rows,
        counts.get("rag_and_multihop", 0) + wiki_long_target,
        salt="v3-2wiki",
    )
    wiki_selected.sort(key=lambda row: stable_digest(row["task_id"], salt="wiki-partition"))
    wiki_long = wiki_selected[:wiki_long_target]
    wiki_rag = wiki_selected[wiki_long_target:]

    coig_target = counts.get("direct_answer_and_abstention", 0)
    coig_path = raw_root / "coig_exam/exam_instructions.jsonl"
    coig_heap: list[tuple[int, int, dict[str, Any]]] = []
    with coig_path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            if str(index) in excluded_ids["coig_exam"]:
                continue
            row = json.loads(line)
            if not str(row.get("textbox_answer", "")).strip() or not str(row.get("textbox_question", "")).strip():
                continue
            key = int(stable_digest(str(index), salt="v3-coig"), 16)
            item = (-key, index, row)
            if len(coig_heap) < coig_target:
                heapq.heappush(coig_heap, item)
            elif item > coig_heap[0]:
                heapq.heapreplace(coig_heap, item)
    if len(coig_heap) < coig_target:
        raise RuntimeError(f"only {len(coig_heap)} COIG rows available; need {coig_target}")

    bundles = [convert_function_candidate(row, "function_calling") for row in function_selected]
    bundles.extend(convert_function_candidate(row, "cross_tool") for row in cross_selected)
    bundles.extend(convert_search_candidate(row, "rag_and_multihop") for row in wiki_rag)
    bundles.extend(
        convert_search_candidate(row, "long_horizon_and_deep_research")
        for row in itertools.chain(wiki_long, qasper_rows)
    )
    bundles.extend(
        convert_coig_candidate(index, row) for _, index, row in sorted(coig_heap, key=lambda item: (-item[0], item[1]))
    )
    return bundles


def build_custom(counts: dict[str, int]) -> list[dict[str, Any]]:
    bundles = []
    for family, count in counts.items():
        factory = CUSTOM_FACTORIES[family]
        bundles.extend(factory(index) for index in range(count))
    return bundles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-count", type=int, default=DEFAULT_CANDIDATES)
    parser.add_argument("--raw-root", type=Path, default=PROJECT_ROOT / "datasets/raw/open_source")
    parser.add_argument(
        "--runtime-sft",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/runtime_sft_v3/selected.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/agent_rl_v3_candidate",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.candidate_count < 80:
        raise ValueError("candidate-count must be at least 80")
    external_counts, custom_counts = allocation(args.candidate_count)
    staging = args.output.with_name(args.output.name + ".building")
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(f"output exists; pass --overwrite: {args.output}")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    bundles = build_external(
        raw_root=args.raw_root,
        runtime_sft=args.runtime_sft,
        counts=external_counts,
    )
    bundles.extend(build_custom(custom_counts))
    if len(bundles) != args.candidate_count:
        raise RuntimeError(f"candidate count mismatch: {len(bundles)} != {args.candidate_count}")
    bundles.sort(key=lambda row: stable_digest(row["task"]["task_id"], salt="candidate-order"))

    tasks: list[dict[str, Any]] = []
    verifiers: list[dict[str, Any]] = []
    witnesses: list[dict[str, Any]] = []
    environment_manifest = []
    for bundle in bundles:
        task = bundle["task"]
        task_id_value = task["task_id"]
        environment_path = staging / "environments" / f"{task_id_value}.json"
        write_json(environment_path, bundle["environment"])
        tasks.append(task)
        verifiers.append(bundle["verifier"])
        witnesses.append(bundle["witness"])
        environment_manifest.append({"task_id": task_id_value, "environment_sha256": sha256(environment_path)})

    write_jsonl(staging / "tasks/candidate.jsonl", tasks)
    write_jsonl(staging / "verifiers/candidate.jsonl", verifiers)
    write_jsonl(staging / "audit/witnesses.jsonl", witnesses)
    write_jsonl(staging / "environment-manifest.jsonl", environment_manifest)

    family_counts = Counter(row["metadata"]["family"] for row in tasks)
    origin_counts = Counter(row["metadata"]["origin"] for row in tasks)
    source_counts = Counter(row["metadata"]["source_dataset"] for row in tasks)
    unique_groups = {row["metadata"]["source_group_id"] for row in tasks}
    manifest = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "dataset_revision": "agent-rl-v3-candidate.1",
        "status": "CANDIDATE_STATIC_QA_PENDING",
        "candidate_tasks": len(tasks),
        "target_candidate_tasks": args.candidate_count,
        "family_mix_target": FAMILY_MIX,
        "family_counts": dict(sorted(family_counts.items())),
        "external_counts_target": external_counts,
        "custom_counts_target": custom_counts,
        "source_counts": dict(sorted(source_counts.items())),
        "origin_counts": dict(sorted(origin_counts.items())),
        "unique_source_groups": len(unique_groups),
        "studyhub_share": round(
            sum(count for origin, count in origin_counts.items() if origin.startswith("training_only")) / len(tasks),
            6,
        ),
        "runtime_sft_selected_sha256": sha256(args.runtime_sft),
        "benchmark": {
            "version": "studyhub-agentbench-v2",
            "revision": "2.0.0",
            "manifest_sha256": "da804b10f53dec585255598c3e256445b8ade3acf35fd8c766ca0ab4d759c88b",
            "sealed_task_files_read": False,
            "custom_source_namespace": "rlv3-*",
        },
        "oracle_policy": {
            "public_task_has_answer": False,
            "public_task_has_verifier": False,
            "hidden_verifier_has_gold_path": False,
            "solvability_witness_is_rollout_visible": False,
            "reward_uses_path_equality": False,
        },
        "tasks_sha256": sha256(staging / "tasks/candidate.jsonl"),
        "verifiers_sha256": sha256(staging / "verifiers/candidate.jsonl"),
        "witnesses_sha256": sha256(staging / "audit/witnesses.jsonl"),
        "environment_manifest_sha256": sha256(staging / "environment-manifest.jsonl"),
    }
    write_json(staging / "manifest.json", manifest)
    if args.output.exists():
        shutil.rmtree(args.output)
    staging.replace(args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
