#!/usr/bin/env python3
"""Build a training-only, architecture-aligned candidate pool for strict OPD."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for entry in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from training.rl.dataset_v3 import (  # noqa: E402
    budget_for,
    validate_hidden_verifier,
    validate_public_task,
)

TRAIN_TASK_FILE = Path("tasks/train.jsonl")
TRAIN_VERIFIER_FILE = Path("verifiers/train.jsonl")
PROHIBITED_FAMILIES = frozenset({"long_horizon_and_deep_research"})
PROHIBITED_BUDGETS = frozenset({"research"})
PROHIBITED_TOOLS = frozenset({"web_fetch"})
ALLOWED_SPLIT = "train"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+|[\u3400-\u9fff]", value.casefold()))


def text_hash(value: str) -> str:
    return hashlib.sha256(normalized_text(value).encode("utf-8")).hexdigest()


def text_terms(value: str) -> set[str]:
    return set(normalized_text(value).split())


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(canonical(row) + "\n")
    os.replace(temporary, path)


def record_groups(record: dict[str, Any]) -> set[str]:
    groups: set[str] = set()
    for key in ("group_id", "source_group_id", "conversation_group"):
        value = record.get(key)
        if value not in (None, ""):
            groups.add(str(value))
    for key in ("source_group_ids", "group_ids"):
        value = record.get(key)
        if isinstance(value, list):
            groups.update(map(str, value))
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        groups.update(record_groups(metadata))
    return groups


def record_prompts(record: dict[str, Any]) -> list[str]:
    prompts: list[str] = []
    for key in ("goal", "user_request", "instruction", "question"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            prompts.append(value)
    for message in record.get("messages", []):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                prompts.append(content)
    return prompts


def load_blocklist(
    paths: list[Path],
) -> tuple[set[str], set[str], set[str], list[set[str]]]:
    task_ids: set[str] = set()
    groups: set[str] = set()
    prompt_hashes: set[str] = set()
    prompt_terms: list[set[str]] = []
    for path in paths:
        if not path.is_file():
            continue
        for row in read_jsonl(path):
            for key in ("task_id", "id"):
                value = row.get(key)
                if value not in (None, ""):
                    task_ids.add(str(value))
            groups.update(record_groups(row))
            for prompt in record_prompts(row):
                prompt_hashes.add(text_hash(prompt))
                prompt_terms.append(text_terms(prompt))
    return task_ids, groups, prompt_hashes, prompt_terms


def benchmark_records(project_root: Path) -> list[dict[str, Any]]:
    root = project_root / "benchmarks/studyhub-agent-v2"
    rows: list[dict[str, Any]] = []
    for split in ("regression", "development", "calibration_challenge"):
        path = root / "tasks" / f"{split}.jsonl"
        if path.is_file():
            rows.extend(read_jsonl(path))
    return rows


def environment_tools(environment: dict[str, Any]) -> set[str]:
    schemas = environment.get("tool_schemas")
    if isinstance(schemas, list) and schemas:
        return {str(row["name"]) for row in schemas}
    return set(map(str, environment.get("available_tools", [])))


def validate_candidate(
    task: dict[str, Any],
    verifier: dict[str, Any],
    *,
    blocked_task_ids: set[str],
    blocked_groups: set[str],
    blocked_prompt_hashes: set[str],
    blocked_prompt_terms_by_size: dict[int, list[set[str]]],
) -> list[str]:
    failures: list[str] = []
    try:
        validate_public_task(task)
        validate_hidden_verifier(verifier)
    except (KeyError, TypeError, ValueError) as error:
        return [f"schema:{type(error).__name__}"]
    task_id = str(task["task_id"])
    metadata = dict(task["metadata"])
    family = str(metadata["family"])
    budget = str(task["budget_tier"])
    tools = set(map(str, task["available_tools"]))
    groups = record_groups(task)
    goal = str(task["goal"])
    if metadata.get("split") != ALLOWED_SPLIT:
        failures.append("not_train_split")
    if family in PROHIBITED_FAMILIES:
        failures.append("long_horizon_family")
    if budget in PROHIBITED_BUDGETS:
        failures.append("research_budget")
    if budget_for(budget)["max_model_turns"] < 1:
        failures.append("invalid_budget")
    if tools & PROHIBITED_TOOLS:
        failures.append("legacy_redundant_tool")
    if task_id in blocked_task_ids:
        failures.append("blocked_task_id")
    if not groups:
        failures.append("missing_source_group")
    if groups & blocked_groups:
        failures.append("blocked_source_group")
    goal_hash = text_hash(goal)
    if goal_hash in blocked_prompt_hashes:
        failures.append("exact_prompt_overlap")
    goal_terms = text_terms(goal)
    minimum_size = max(1, int(len(goal_terms) * 0.90))
    maximum_size = max(minimum_size, int(len(goal_terms) / 0.90) + 1)
    near_candidates = (
        other
        for size in range(minimum_size, maximum_size + 1)
        for other in blocked_prompt_terms_by_size.get(size, ())
    )
    if any(jaccard(goal_terms, other) >= 0.90 for other in near_candidates):
        failures.append("near_prompt_overlap")
    return failures


def validate_environment(
    task: dict[str, Any], verifier: dict[str, Any], environment: dict[str, Any]
) -> list[str]:
    failures: list[str] = []
    task_id = str(task["task_id"])
    tools = set(map(str, task["available_tools"]))
    if environment.get("schema_version") != "studyhub.rl-environment.v3":
        failures.append("environment_schema")
    if str(environment.get("task_id")) != task_id:
        failures.append("environment_task_mismatch")
    if str(verifier.get("task_id")) != task_id:
        failures.append("verifier_task_mismatch")
    if tools != environment_tools(environment):
        failures.append("tool_surface_mismatch")
    return failures


def stratified_probe(
    rows: list[dict[str, Any]], size: int, seed: int
) -> list[dict[str, Any]]:
    if size > len(rows):
        raise ValueError("novelty probe exceeds candidate rows")
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_family[str(row["metadata"]["family"])].append(row)
    rng = random.Random(seed)
    for family_rows in by_family.values():
        family_rows.sort(key=lambda row: str(row["task_id"]))
        rng.shuffle(family_rows)
    targets = {
        family: min(
            len(family_rows), max(1, round(size * len(family_rows) / len(rows)))
        )
        for family, family_rows in by_family.items()
    }
    while sum(targets.values()) > size:
        family = max(targets, key=lambda key: (targets[key], key))
        targets[family] -= 1
    while sum(targets.values()) < size:
        eligible = [
            key for key, values in by_family.items() if targets[key] < len(values)
        ]
        family = max(
            eligible, key=lambda key: (len(by_family[key]) - targets[key], key)
        )
        targets[family] += 1
    selected = [
        row for family, values in by_family.items() for row in values[: targets[family]]
    ]
    return sorted(selected, key=lambda row: str(row["task_id"]))


def hardlink_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(
            "/data/chengjin/studyhub/studyhub-agent/datasets/processed/agent_rl_v3"
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/opd_prompt_pool_v1",
    )
    parser.add_argument("--blocklist", type=Path, action="append", default=[])
    parser.add_argument("--candidate-min", type=int, default=4000)
    parser.add_argument("--candidate-max", type=int, default=8000)
    parser.add_argument("--novelty-size", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20260827)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()
    if output_root == source_root or source_root in output_root.parents:
        raise RuntimeError("OPD output must not modify the immutable source dataset")
    required = [
        source_root / TRAIN_TASK_FILE,
        source_root / TRAIN_VERIFIER_FILE,
        source_root / "manifest.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing OPD source files: {missing}")

    benchmark_rows = benchmark_records(PROJECT_ROOT)
    implicit_blocklists = [
        Path(
            "/data/chengjin/studyhub/studyhub-agent/datasets/interim/open_agentic_sft_v2/selected.jsonl"
        ),
        Path(
            "/data/chengjin/studyhub/studyhub-agent/datasets/interim/qwen35_4b_sft2_codex_retention_v1/selected.jsonl"
        ),
        Path(
            "/data/chengjin/studyhub-sft2-worktree/studyhub-agent/datasets/interim/codex_hermes_teacher_v1_full/task_specs.jsonl"
        ),
    ]
    blocked_task_ids: set[str] = set()
    blocked_groups: set[str] = set()
    blocked_hashes: set[str] = set()
    blocked_terms: list[set[str]] = []
    benchmark_ids, benchmark_groups, benchmark_hashes, benchmark_terms = (
        load_blocklist_from_rows(benchmark_rows)
    )
    blocked_task_ids.update(benchmark_ids)
    blocked_groups.update(benchmark_groups)
    blocked_hashes.update(benchmark_hashes)
    blocked_terms.extend(benchmark_terms)
    extra = [
        path.resolve()
        for path in [*implicit_blocklists, *args.blocklist]
        if path.is_file()
    ]
    extra_ids, extra_groups, extra_hashes, extra_terms = load_blocklist(extra)
    blocked_task_ids.update(extra_ids)
    blocked_groups.update(extra_groups)
    blocked_hashes.update(extra_hashes)
    blocked_terms.extend(extra_terms)
    blocked_terms_by_size: dict[int, list[set[str]]] = defaultdict(list)
    for terms in blocked_terms:
        blocked_terms_by_size[len(terms)].append(terms)

    verifiers = {
        str(row["task_id"]): row
        for row in read_jsonl(source_root / TRAIN_VERIFIER_FILE)
    }
    tasks = read_jsonl(source_root / TRAIN_TASK_FILE)
    candidates: list[dict[str, Any]] = []
    drop_reasons: Counter[str] = Counter()
    seen_ids: set[str] = set()
    seen_goals: set[str] = set()
    for task in tasks:
        task_id = str(task.get("task_id", ""))
        if task_id in seen_ids:
            drop_reasons["duplicate_task_id"] += 1
            continue
        verifier = verifiers.get(task_id)
        if verifier is None:
            drop_reasons["missing_hidden_record"] += 1
            continue
        failures = validate_candidate(
            task,
            verifier,
            blocked_task_ids=blocked_task_ids,
            blocked_groups=blocked_groups,
            blocked_prompt_hashes=blocked_hashes,
            blocked_prompt_terms_by_size=blocked_terms_by_size,
        )
        if failures:
            drop_reasons.update(failures)
            continue
        environment_path = source_root / "environments" / f"{task_id}.json"
        if not environment_path.is_file():
            drop_reasons["missing_hidden_record"] += 1
            continue
        environment = json.loads(environment_path.read_text(encoding="utf-8"))
        failures = validate_environment(task, verifier, environment)
        if failures:
            drop_reasons.update(failures)
            continue
        goal_hash = text_hash(str(task["goal"]))
        if goal_hash in seen_goals:
            drop_reasons["duplicate_goal"] += 1
            continue
        seen_ids.add(task_id)
        seen_goals.add(goal_hash)
        candidates.append(task)

    candidates.sort(
        key=lambda row: hashlib.sha256(
            f"{args.seed}:{row['task_id']}".encode()
        ).hexdigest()
    )
    candidates = candidates[: args.candidate_max]
    if not args.candidate_min <= len(candidates) <= args.candidate_max:
        raise RuntimeError(
            f"OPD candidate gate failed: {len(candidates)} not in "
            f"[{args.candidate_min}, {args.candidate_max}]"
        )
    probe = stratified_probe(candidates, args.novelty_size, args.seed)

    if output_root.exists():
        shutil.rmtree(output_root)
    (output_root / "tasks").mkdir(parents=True)
    (output_root / "verifiers").mkdir(parents=True)
    (output_root / "environments").mkdir(parents=True)
    write_jsonl(output_root / "tasks/train.jsonl", candidates)
    write_jsonl(output_root / "tasks/novelty_probe.jsonl", probe)
    candidate_ids = {str(row["task_id"]) for row in candidates}
    write_jsonl(
        output_root / "verifiers/train.jsonl",
        (verifiers[task_id] for task_id in sorted(candidate_ids)),
    )
    for task_id in sorted(candidate_ids):
        hardlink_or_copy(
            source_root / "environments" / f"{task_id}.json",
            output_root / "environments" / f"{task_id}.json",
        )

    family_counts = Counter(str(row["metadata"]["family"]) for row in candidates)
    budget_counts = Counter(str(row["budget_tier"]) for row in candidates)
    probe_family_counts = Counter(str(row["metadata"]["family"]) for row in probe)
    manifest = {
        "schema_version": "studyhub.opd-prompt-pool-candidate.v1",
        "status": "CANDIDATE_AND_NOVELTY_PROBE_PASS",
        "seed": args.seed,
        "source": {
            "root": str(source_root),
            "dataset_manifest_sha256": sha256(source_root / "manifest.json"),
            "tasks_sha256": sha256(source_root / TRAIN_TASK_FILE),
            "verifiers_sha256": sha256(source_root / TRAIN_VERIFIER_FILE),
            "split_read": ALLOWED_SPLIT,
            "validation_read": False,
            "protocol_holdout_read": False,
        },
        "candidate_rows": len(candidates),
        "novelty_probe_rows": len(probe),
        "candidate_family_counts": dict(sorted(family_counts.items())),
        "candidate_budget_counts": dict(sorted(budget_counts.items())),
        "probe_family_counts": dict(sorted(probe_family_counts.items())),
        "drop_reasons": dict(drop_reasons.most_common()),
        "blocked_inputs": [str(path) for path in extra],
        "blocked_task_ids": len(blocked_task_ids),
        "blocked_source_groups": len(blocked_groups),
        "prohibited_tools": sorted(PROHIBITED_TOOLS),
        "prohibited_families": sorted(PROHIBITED_FAMILIES),
        "prohibited_budget_tiers": sorted(PROHIBITED_BUDGETS),
        "lineage": {
            "candidate_tasks_sha256": sha256(output_root / "tasks/train.jsonl"),
            "novelty_probe_sha256": sha256(output_root / "tasks/novelty_probe.jsonl"),
            "candidate_verifiers_sha256": sha256(output_root / "verifiers/train.jsonl"),
        },
        "selected_prompt_pool": "PENDING_T9_VS_M2_NOVELTY_GATE",
    }
    write_json(output_root / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def load_blocklist_from_rows(
    rows: Iterable[dict[str, Any]],
) -> tuple[set[str], set[str], set[str], list[set[str]]]:
    task_ids: set[str] = set()
    groups: set[str] = set()
    hashes: set[str] = set()
    terms: list[set[str]] = []
    for row in rows:
        value = row.get("task_id")
        if value not in (None, ""):
            task_ids.add(str(value))
        groups.update(record_groups(row))
        for prompt in record_prompts(row):
            hashes.add(text_hash(prompt))
            terms.append(text_terms(prompt))
    return task_ids, groups, hashes, terms


if __name__ == "__main__":
    raise SystemExit(main())
