#!/usr/bin/env python3
"""Verify Agent RL v3 candidates and build the 10k post-QA dataset."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from training.rl.dataset_v3 import (  # noqa: E402
    DATASET_SCHEMA_VERSION,
    FAMILY_MIX,
    budget_for,
    validate_hidden_verifier,
    validate_public_task,
)
from training.rl.environment_v3 import (  # noqa: E402
    ENVIRONMENT_V3_SCHEMA,
    TrainingTaskEnvironmentV3,
)
from training.rl.reward_v3 import evaluate_reward_v3  # noqa: E402
from training.rl.task_factory_v3 import stable_digest  # noqa: E402

BASE_FINAL_CUSTOM = {
    "function_calling": 400,
    "rag_and_multihop": 550,
    "web": 1200,
    "memory": 1200,
    "cross_tool": 700,
    "recovery_and_acl": 1200,
    "long_horizon_and_deep_research": 500,
    "direct_answer_and_abstention": 250,
}
BASE_FINAL_EXTERNAL = {
    "function_calling": 800,
    "rag_and_multihop": 1250,
    "web": 0,
    "memory": 0,
    "cross_tool": 900,
    "recovery_and_acl": 0,
    "long_horizon_and_deep_research": 500,
    "direct_answer_and_abstention": 550,
}
DEFAULT_TARGET = 10000
EXPECTED_BENCHMARK_SHA = "da804b10f53dec585255598c3e256445b8ade3acf35fd8c766ca0ab4d759c88b"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"non-object JSON row at {path}:{line_number}")
            rows.append(value)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _is_custom(task: dict[str, Any]) -> bool:
    return str(task["metadata"]["origin"]).startswith("training_only")


def _scale(base: dict[str, int], total: int) -> dict[str, int]:
    denominator = sum(base.values())
    raw = {key: total * value / denominator for key, value in base.items()}
    result = {key: int(value) for key, value in raw.items()}
    remainder = total - sum(result.values())
    order = sorted(base, key=lambda key: (-(raw[key] - result[key]), key))
    for key in order[:remainder]:
        result[key] += 1
    return result


def _select(
    tasks: list[dict[str, Any]],
    target: int,
) -> list[dict[str, Any]]:
    if target == DEFAULT_TARGET:
        custom_quota = BASE_FINAL_CUSTOM
        external_quota = BASE_FINAL_EXTERNAL
    else:
        custom_quota = _scale(BASE_FINAL_CUSTOM, round(target * 0.60))
        external_quota = _scale(BASE_FINAL_EXTERNAL, target - round(target * 0.60))
    by_lane: dict[tuple[str, bool], list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        by_lane[(str(task["metadata"]["family"]), _is_custom(task))].append(task)
    selected = []
    for family in FAMILY_MIX:
        for custom, quota in ((True, custom_quota.get(family, 0)), (False, external_quota.get(family, 0))):
            rows = sorted(
                by_lane[(family, custom)],
                key=lambda row: stable_digest(row["task_id"], salt="post-qa-selection"),
            )
            if len(rows) < quota:
                raise RuntimeError(f"insufficient {'custom' if custom else 'external'} {family}: {len(rows)} < {quota}")
            selected.extend(rows[:quota])
    if len(selected) != target:
        raise RuntimeError(f"post-QA selection count mismatch: {len(selected)} != {target}")
    return selected


def _assign_splits(tasks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    lanes: dict[tuple[str, bool], list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        lanes[(task["metadata"]["family"], _is_custom(task))].append(task)
    splits = {"train": [], "validation": [], "protocol_holdout": []}
    for lane, rows in sorted(lanes.items()):
        rows.sort(key=lambda row: stable_digest(row["task_id"], salt=f"split:{lane}"))
        validation = round(len(rows) * 0.10)
        holdout = round(len(rows) * 0.10)
        train = len(rows) - validation - holdout
        offset = 0
        for split, count in (
            ("train", train),
            ("validation", validation),
            ("protocol_holdout", holdout),
        ):
            for source in rows[offset : offset + count]:
                task = json.loads(json.dumps(source, ensure_ascii=False))
                task["metadata"]["split"] = split
                splits[split].append(task)
            offset += count
    for rows in splits.values():
        rows.sort(key=lambda row: stable_digest(row["task_id"], salt="final-order"))
    return splits


async def _run_witness(
    *,
    candidate_root: Path,
    task: dict[str, Any],
    verifier: dict[str, Any],
    witness: dict[str, Any],
    alternative: bool,
) -> dict[str, Any]:
    task_id = task["task_id"]
    action_key = "alternative_actions" if alternative else "actions"
    final_key = "alternative_final_answer" if alternative else "final_answer"
    actions = list(witness.get(action_key, []))
    final_answer = str(witness.get(final_key, ""))
    if alternative and not actions:
        return {"task_id": task_id, "mode": "alternative", "status": "NOT_APPLICABLE"}
    observations = []
    try:
        environment = TrainingTaskEnvironmentV3.from_root(candidate_root, task_id)
        for action in actions:
            observations.append(await environment.execute(str(action["name"]), dict(action["arguments"])))
        result = evaluate_reward_v3(
            final_answer=final_answer,
            trace=environment.trace_dict(),
            final_state=environment.state_snapshot(),
            verifier=verifier,
        )
    except (KeyError, TypeError, ValueError) as error:
        return {
            "task_id": task_id,
            "mode": "alternative" if alternative else "canonical",
            "status": "FAIL",
            "strict_success": False,
            "reward": -1.0,
            "hard_gate_reasons": [f"qa_exception:{type(error).__name__}:{error}"],
            "tool_calls": len(actions),
            "observation_sha256": hashlib.sha256("\n".join(observations).encode()).hexdigest(),
        }
    return {
        "task_id": task_id,
        "mode": "alternative" if alternative else "canonical",
        "status": "PASS" if result.strict_success else "FAIL",
        "strict_success": result.strict_success,
        "reward": result.total,
        "hard_gate_reasons": list(result.hard_gate_reasons),
        "tool_calls": len(actions),
        "observation_sha256": hashlib.sha256("\n".join(observations).encode()).hexdigest(),
    }


async def verify_witnesses(
    candidate_root: Path,
    tasks: list[dict[str, Any]],
    verifiers: dict[str, dict[str, Any]],
    witnesses: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for index, task in enumerate(tasks, start=1):
        task_id = task["task_id"]
        rows.append(
            await _run_witness(
                candidate_root=candidate_root,
                task=task,
                verifier=verifiers[task_id],
                witness=witnesses[task_id],
                alternative=False,
            )
        )
        if witnesses[task_id].get("alternative_actions"):
            rows.append(
                await _run_witness(
                    candidate_root=candidate_root,
                    task=task,
                    verifier=verifiers[task_id],
                    witness=witnesses[task_id],
                    alternative=True,
                )
            )
        if index % 1000 == 0:
            print(f"verified witnesses: {index}/{len(tasks)}", file=sys.stderr)
    return rows


def _static_validate(
    root: Path,
    tasks: list[dict[str, Any]],
    verifiers: dict[str, dict[str, Any]],
    witnesses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    errors = []
    task_ids = [str(row["task_id"]) for row in tasks]
    if len(task_ids) != len(set(task_ids)):
        errors.append("duplicate task_id")
    normalized_goals = [" ".join(str(row["goal"]).casefold().split()) for row in tasks]
    groups = [str(row["metadata"]["source_group_id"]) for row in tasks]
    if len(groups) != len(set(groups)):
        errors.append("candidate source groups are not unique")
    for task in tasks:
        task_id = task["task_id"]
        try:
            validate_public_task(task)
            validate_hidden_verifier(verifiers[task_id])
        except (KeyError, ValueError) as error:
            errors.append(f"{task_id}: {error}")
            continue
        environment_path = root / "environments" / f"{task_id}.json"
        if not environment_path.exists():
            errors.append(f"{task_id}: missing environment")
            continue
        environment = json.loads(environment_path.read_text(encoding="utf-8"))
        if environment.get("schema_version") != ENVIRONMENT_V3_SCHEMA:
            errors.append(f"{task_id}: invalid environment schema")
        if environment.get("task_id") != task_id:
            errors.append(f"{task_id}: environment ID mismatch")
        environment_tools = (
            [row["name"] for row in environment.get("tool_schemas", [])]
            if environment.get("environment_kind") == "fixture"
            else list(environment.get("available_tools", []))
        )
        if set(environment_tools) != set(task["available_tools"]):
            errors.append(f"{task_id}: public/environment tool mismatch")
        budget = budget_for(task["budget_tier"])
        if int(environment.get("max_tool_calls", budget["max_tool_calls"])) > budget["max_tool_calls"]:
            errors.append(f"{task_id}: environment exceeds public tool budget")
        if witnesses[task_id].get("rollout_visible") is not False:
            errors.append(f"{task_id}: witness visibility is not false")
    template_counts = Counter(row["metadata"]["template_id"] for row in tasks)
    source_counts = Counter(row["metadata"]["source_dataset"] for row in tasks)
    family_counts = Counter(row["metadata"]["family"] for row in tasks)
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "tasks": len(tasks),
        "unique_tasks": len(set(task_ids)),
        "unique_source_groups": len(set(groups)),
        "exact_goal_duplicates": len(tasks) - len(set(normalized_goals)),
        "semantic_template_clusters": len(template_counts),
        "largest_template_cluster": max(template_counts.values(), default=0),
        "largest_template_cluster_share": round(max(template_counts.values(), default=0) / max(1, len(tasks)), 6),
        "family_counts": dict(sorted(family_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/agent_rl_v3_candidate",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "datasets/processed/agent_rl_v3",
    )
    parser.add_argument("--target-count", type=int, default=DEFAULT_TARGET)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tasks = read_jsonl(args.candidate / "tasks/candidate.jsonl")
    verifier_rows = read_jsonl(args.candidate / "verifiers/candidate.jsonl")
    witness_rows = read_jsonl(args.candidate / "audit/witnesses.jsonl")
    verifiers = {row["task_id"]: row for row in verifier_rows}
    witnesses = {row["task_id"]: row for row in witness_rows}
    if set(verifiers) != {row["task_id"] for row in tasks} or set(witnesses) != set(verifiers):
        raise RuntimeError("task/verifier/witness identity sets differ")
    static = _static_validate(args.candidate, tasks, verifiers, witnesses)
    if static["status"] != "PASS":
        raise RuntimeError(f"static candidate validation failed: {static['errors'][:5]}")

    witness_rows = asyncio.run(verify_witnesses(args.candidate, tasks, verifiers, witnesses))
    canonical_failures = [row for row in witness_rows if row["status"] == "FAIL" and row["mode"] == "canonical"]
    alternative_failures = [row for row in witness_rows if row["status"] == "FAIL" and row["mode"] == "alternative"]
    alternative_fail_ids = {row["task_id"] for row in alternative_failures}
    canonical_pass_ids = {
        row["task_id"] for row in witness_rows if row["status"] == "PASS" and row["mode"] == "canonical"
    }
    witness_audit = {
        "schema_version": "studyhub.rl-solvability-audit.v3",
        "candidate_tasks": len(tasks),
        "canonical_pass": sum(row["status"] == "PASS" and row["mode"] == "canonical" for row in witness_rows),
        "canonical_fail": sum(row["status"] == "FAIL" and row["mode"] == "canonical" for row in witness_rows),
        "alternative_applicable": sum(row["mode"] == "alternative" for row in witness_rows),
        "alternative_pass": sum(row["status"] == "PASS" and row["mode"] == "alternative" for row in witness_rows),
        "canonical_rejected": len(canonical_failures),
        "alternative_fail": len(alternative_failures),
        "canonical_failures": canonical_failures[:100],
        "alternative_failures": alternative_failures[:100],
        "status": "PASS" if len(canonical_pass_ids) >= args.target_count else "INSUFFICIENT",
    }
    write_json(args.candidate / "audit/static-qa.json", static)
    write_json(args.candidate / "audit/witness-audit.json", witness_audit)
    if args.verify_only:
        print(json.dumps({"static": static, "witness": witness_audit}, ensure_ascii=False, indent=2))
        return 0

    eligible_tasks = []
    seen_goals: set[str] = set()
    for row in sorted(tasks, key=lambda item: stable_digest(item["task_id"], salt="goal-dedup")):
        if row["task_id"] not in canonical_pass_ids:
            continue
        if row["task_id"] in alternative_fail_ids:
            continue
        normalized_goal = " ".join(str(row["goal"]).casefold().split())
        if normalized_goal in seen_goals:
            continue
        seen_goals.add(normalized_goal)
        eligible_tasks.append(row)
    if len(eligible_tasks) < args.target_count:
        raise RuntimeError(f"only {len(eligible_tasks)} canonical witnesses passed; need {args.target_count}")
    selected = _select(eligible_tasks, args.target_count)
    splits = _assign_splits(selected)
    staging = args.output.with_name(args.output.name + ".building")
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(f"output exists; pass --overwrite: {args.output}")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    selected_ids = {row["task_id"] for row in selected}
    for task_id in sorted(selected_ids):
        source = args.candidate / "environments" / f"{task_id}.json"
        target = staging / "environments" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    selected_verifiers = {task_id: verifiers[task_id] for task_id in selected_ids}
    selected_witnesses = {task_id: witnesses[task_id] for task_id in selected_ids}
    split_groups = {}
    for split, split_tasks in splits.items():
        ids = {row["task_id"] for row in split_tasks}
        write_jsonl(staging / f"tasks/{split}.jsonl", split_tasks)
        write_jsonl(
            staging / f"verifiers/{split}.jsonl",
            [selected_verifiers[task_id] for task_id in sorted(ids)],
        )
        write_jsonl(
            staging / f"audit/witnesses-{split}.jsonl",
            [selected_witnesses[task_id] for task_id in sorted(ids)],
        )
        split_groups[split] = {row["metadata"]["source_group_id"] for row in split_tasks}

    # The Arrow transport carries only the complete public task. Hidden
    # verifiers and protocol-holdout rows remain outside the training dataset.
    from datasets import Dataset, DatasetDict

    hf_splits = {}
    for split in ("train", "validation"):
        transport_rows = [
            {
                "task_id": row["task_id"],
                "family": row["metadata"]["family"],
                "source_dataset": row["metadata"]["source_dataset"],
                "source_group_id": row["metadata"]["source_group_id"],
                "budget_tier": row["budget_tier"],
                "task_json": json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            }
            for row in splits[split]
        ]
        hf_splits[split] = Dataset.from_list(transport_rows)
    DatasetDict(hf_splits).save_to_disk(str(staging / "hf_dataset"))
    overlap = {
        "train_validation": len(split_groups["train"] & split_groups["validation"]),
        "train_holdout": len(split_groups["train"] & split_groups["protocol_holdout"]),
        "validation_holdout": len(split_groups["validation"] & split_groups["protocol_holdout"]),
    }
    if any(overlap.values()):
        raise RuntimeError(f"source-group split overlap: {overlap}")

    # The benchmark manifest is read only for its immutable hash. No Sealed task,
    # environment, grader or oracle file is opened by this script.
    benchmark_manifest = PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json"
    benchmark_sha = sha256(benchmark_manifest)
    if benchmark_sha != EXPECTED_BENCHMARK_SHA:
        raise RuntimeError(f"frozen Benchmark v2 hash drift: {benchmark_sha}")

    final_family = Counter(row["metadata"]["family"] for row in selected)
    final_origin = Counter("custom" if _is_custom(row) else "external" for row in selected)
    final_sources = Counter(row["metadata"]["source_dataset"] for row in selected)
    final_budgets = Counter(row["budget_tier"] for row in selected)
    final_tool_signatures = Counter(
        "+".join(sorted(map(str, row["available_tools"]))) or "NO_TOOLS" for row in selected
    )
    final_environment_kinds = Counter(
        json.loads((staging / "environments" / f"{row['task_id']}.json").read_text(encoding="utf-8"))[
            "environment_kind"
        ]
        for row in selected
    )
    selected_alternative_witnesses = sum(
        bool(selected_witnesses[row["task_id"]].get("alternative_actions")) for row in selected
    )
    manifest = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "dataset_revision": "agent-rl-v3-post-qa.1",
        "status": "STATIC_QA_PASSED_LEARNABILITY_NOT_RUN",
        "candidate_tasks": len(tasks),
        "post_qa_tasks": len(selected),
        "split_counts": {split: len(rows) for split, rows in splits.items()},
        "family_counts": dict(sorted(final_family.items())),
        "origin_counts": dict(sorted(final_origin.items())),
        "source_counts": dict(sorted(final_sources.items())),
        "budget_tier_counts": dict(sorted(final_budgets.items())),
        "tool_signature_counts": dict(sorted(final_tool_signatures.items())),
        "environment_kind_counts": dict(sorted(final_environment_kinds.items())),
        "studyhub_share": round(final_origin["custom"] / len(selected), 6),
        "custom_data_character": "deterministic_training_simulator_not_production_traffic",
        "unique_source_groups": len({row["metadata"]["source_group_id"] for row in selected}),
        "exact_goal_duplicates": len(selected)
        - len({" ".join(str(row["goal"]).casefold().split()) for row in selected}),
        "selected_alternative_witnesses": selected_alternative_witnesses,
        "source_group_split_overlap": overlap,
        "hf_transport": {
            "schema_version": "studyhub.agent-rl-hf-transport.v3",
            "splits": {split: len(splits[split]) for split in ("train", "validation")},
            "protocol_holdout_exposed": False,
            "task_json_contains_public_contract_only": True,
            "tree_sha256": tree_sha256(staging / "hf_dataset"),
        },
        "candidate_manifest_sha256": sha256(args.candidate / "manifest.json"),
        "runtime_sft_selected_sha256": json.loads((args.candidate / "manifest.json").read_text(encoding="utf-8"))[
            "runtime_sft_selected_sha256"
        ],
        "benchmark": {
            "version": "studyhub-agentbench-v2",
            "revision": "2.0.0",
            "manifest_sha256": benchmark_sha,
            "sealed_task_files_read": False,
            "overlap_method": "external-source exclusion plus disjoint rlv3 training namespace",
        },
        "static_qa": static,
        "solvability": witness_audit,
        "learnability": {
            "status": "NOT_RUN",
            "rollouts_per_task": 4,
            "mixed_outcome_destination": "GRPO_MAIN",
            "all_correct_destination": "RETENTION_SET",
            "all_failed_destination": "TEACHER_REPAIR_OR_CURRICULUM",
            "infra_failure_destination": "RETRY_OR_EXCLUDE_NOT_POLICY_REWARD",
        },
        "public_task_oracle_fields": False,
        "hidden_verifier_gold_path_fields": False,
    }
    write_json(staging / "manifest.json", manifest)
    write_json(staging / "audit/static-qa.json", static)
    write_json(staging / "audit/witness-audit.json", witness_audit)
    if args.output.exists():
        shutil.rmtree(args.output)
    staging.replace(args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
