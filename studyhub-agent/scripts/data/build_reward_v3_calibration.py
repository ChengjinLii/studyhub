#!/usr/bin/env python3
"""Build a deterministic 800-case controlled calibration suite for Reward v3."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAMILIES = (
    "function_calling",
    "rag_and_multihop",
    "web",
    "memory",
    "cross_tool",
    "recovery_and_acl",
    "long_horizon_and_deep_research",
    "direct_answer_and_abstention",
)
BASE_PER_FAMILY = 20
ALTERNATIVE_TARGET = 160
EXPECTED_CASES = 800


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_rank(seed: int, *parts: str) -> str:
    return hashlib.sha256(":".join([str(seed), *parts]).encode()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _case(
    task: dict[str, Any],
    case_type: str,
    expected_accept: bool,
    expected_quality: float,
    execution: str,
) -> dict[str, Any]:
    task_id = str(task["task_id"])
    return {
        "schema_version": "studyhub.reward-v3-calibration-case.v1",
        "case_id": f"cal-{stable_rank(0, task_id, case_type)[:20]}",
        "task_id": task_id,
        "family": task["metadata"]["family"],
        "source_group_id": task["metadata"]["source_group_id"],
        "case_type": case_type,
        "expected_accept": expected_accept,
        "expected_quality": expected_quality,
        "execution": execution,
        "split": "protocol_holdout",
        "rollout_visible": False,
        "label_origin": "controlled_programmatic_contract",
    }


def build_cases(
    tasks: list[dict[str, Any]],
    witnesses: dict[str, dict[str, Any]],
    *,
    seed: int,
) -> list[dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        by_family[str(task["metadata"]["family"])].append(task)
    base_tasks = []
    for family in FAMILIES:
        rows = sorted(
            by_family[family],
            key=lambda row: stable_rank(seed, family, str(row["task_id"])),
        )
        if len(rows) < BASE_PER_FAMILY:
            raise RuntimeError(f"insufficient protocol-holdout tasks for {family}")
        base_tasks.extend(rows[:BASE_PER_FAMILY])

    cases = []
    for task in base_tasks:
        cases.extend(
            [
                _case(task, "normal", True, 1.00, "canonical"),
                _case(task, "boundary", False, 0.45, "boundary_mutation"),
                _case(task, "adversarial", False, 0.00, "adversarial_mutation"),
                _case(task, "reward_hacking", False, 0.15, "outcome_without_evidence"),
            ]
        )

    alternatives: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        witness = witnesses[str(task["task_id"])]
        if witness.get("alternative_actions"):
            alternatives[str(task["metadata"]["family"])].append(task)
    for rows in alternatives.values():
        rows.sort(key=lambda row: stable_rank(seed, "alternative", str(row["task_id"])))

    selected_alternatives = []
    families = sorted(alternatives)
    while len(selected_alternatives) < ALTERNATIVE_TARGET:
        progressed = False
        for family in families:
            if alternatives[family]:
                selected_alternatives.append(alternatives[family].pop(0))
                progressed = True
                if len(selected_alternatives) == ALTERNATIVE_TARGET:
                    break
        if not progressed:
            raise RuntimeError("insufficient verified alternative witnesses for calibration")
    cases.extend(_case(task, "alternative_valid_path", True, 0.95, "alternative") for task in selected_alternatives)
    cases.sort(key=lambda row: stable_rank(seed, row["case_id"]))
    if len(cases) != EXPECTED_CASES:
        raise RuntimeError(f"calibration case count mismatch: {len(cases)}")
    if len({row["case_id"] for row in cases}) != EXPECTED_CASES:
        raise RuntimeError("duplicate calibration case IDs")
    return cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "datasets/processed/agent_rl_v3",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/reward_v3_calibration",
    )
    parser.add_argument("--seed", type=int, default=6209)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tasks_path = args.dataset / "tasks/protocol_holdout.jsonl"
    witness_path = args.dataset / "audit/witnesses-protocol_holdout.jsonl"
    tasks = read_jsonl(tasks_path)
    witnesses = {row["task_id"]: row for row in read_jsonl(witness_path)}
    cases = build_cases(tasks, witnesses, seed=args.seed)
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(f"output exists; pass --overwrite: {args.output}")
    staging = args.output.with_name(args.output.name + ".building")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    write_jsonl(staging / "cases.jsonl", cases)
    manifest = {
        "schema_version": "studyhub.reward-v3-calibration-suite.v1",
        "status": "BUILT_NOT_CALIBRATED",
        "seed": args.seed,
        "case_count": len(cases),
        "case_type_counts": dict(sorted(Counter(row["case_type"] for row in cases).items())),
        "family_counts": dict(sorted(Counter(row["family"] for row in cases).items())),
        "unique_task_count": len({row["task_id"] for row in cases}),
        "source_split": "protocol_holdout",
        "human_review": False,
        "teacher_semantic_review": False,
        "controlled_programmatic_labels": True,
        "training_rows": False,
        "sealed_files_read": False,
        "source_manifest_sha256": sha256(args.dataset / "manifest.json"),
        "source_tasks_sha256": sha256(tasks_path),
        "source_witnesses_sha256": sha256(witness_path),
        "cases_sha256": sha256(staging / "cases.jsonl"),
    }
    write_json(staging / "manifest.json", manifest)
    if args.output.exists():
        shutil.rmtree(args.output)
    staging.replace(args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
