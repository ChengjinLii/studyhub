#!/usr/bin/env python3
"""Select a teacher-aligned OPD train/dev pool after the 500-task novelty gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from datasets import Dataset, DatasetDict


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_rank(seed: int, *parts: str) -> str:
    return hashlib.sha256(
        (str(seed) + "\0" + "\0".join(parts)).encode("utf-8")
    ).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def episode_map(path: Path) -> dict[str, dict[str, Any]]:
    rows = read_jsonl(path)
    result = {str(row["task_id"]): row for row in rows}
    if len(result) != len(rows):
        raise RuntimeError(f"duplicate policy-probe task IDs: {path}")
    return result


def verifier_map(path: Path) -> dict[str, dict[str, Any]]:
    rows = read_jsonl(path)
    result = {str(row["task_id"]): row for row in rows}
    if len(result) != len(rows):
        raise RuntimeError(f"duplicate verifier task IDs: {path}")
    return result


def family_scores(
    teacher: dict[str, dict[str, Any]], student: dict[str, dict[str, Any]]
) -> dict[str, dict[str, float]]:
    by_family: dict[str, list[str]] = defaultdict(list)
    for task_id, row in teacher.items():
        by_family[str(row["family"])].append(task_id)
    result = {}
    for family, task_ids in by_family.items():
        teacher_only = sum(
            bool(teacher[key]["strict_success"])
            and not bool(student[key]["strict_success"])
            for key in task_ids
        )
        teacher_success = sum(bool(teacher[key]["strict_success"]) for key in task_ids)
        delta = sum(
            float(teacher[key]["diagnostic_score"])
            - float(student[key]["diagnostic_score"])
            for key in task_ids
        ) / len(task_ids)
        result[family] = {
            "tasks": float(len(task_ids)),
            "teacher_only_rate": teacher_only / len(task_ids),
            "teacher_success_rate": teacher_success / len(task_ids),
            "mean_diagnostic_delta": delta,
        }
    return result


def task_priority(
    task: dict[str, Any],
    *,
    teacher: dict[str, dict[str, Any]],
    student: dict[str, dict[str, Any]],
    family: dict[str, dict[str, float]],
    seed: int,
) -> tuple[Any, ...]:
    task_id = str(task["task_id"])
    family_name = str(task["metadata"]["family"])
    family_row = family[family_name]
    teacher_row = teacher.get(task_id)
    student_row = student.get(task_id)
    if teacher_row is not None and student_row is not None:
        teacher_pass = bool(teacher_row["strict_success"])
        student_pass = bool(student_row["strict_success"])
        delta = float(teacher_row["diagnostic_score"]) - float(
            student_row["diagnostic_score"]
        )
        tier = (
            0
            if teacher_pass and not student_pass
            else 1 if teacher_pass and delta > 0 else 2 if delta > 0 else 4
        )
    else:
        delta = float(family_row["mean_diagnostic_delta"])
        tier = 3 if delta > 0 or family_row["teacher_only_rate"] > 0 else 5
    return (
        tier,
        -float(family_row["teacher_only_rate"]),
        -float(family_row["teacher_success_rate"]),
        -float(family_row["mean_diagnostic_delta"]),
        -delta,
        stable_rank(seed, task_id),
    )


def copy_artifact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def dataset_row(task: dict[str, Any]) -> dict[str, str]:
    metadata = task["metadata"]
    return {
        "task_id": str(task["task_id"]),
        "family": str(metadata["family"]),
        "source_dataset": str(metadata["source_dataset"]),
        "source_group_id": str(metadata["source_group_id"]),
        "budget_tier": str(task["budget_tier"]),
        "task_json": json.dumps(task, ensure_ascii=False, sort_keys=True),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--teacher-episodes", type=Path, required=True)
    parser.add_argument("--student-episodes", type=Path, required=True)
    parser.add_argument("--novelty-gate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-size", type=int, default=2000)
    parser.add_argument("--dev-size", type=int, default=128)
    parser.add_argument("--max-per-source-group", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260827)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1500 <= args.train_size <= 3000:
        raise RuntimeError("OPD train size must remain in the frozen 1500-3000 range")
    candidate_root = args.candidate_root.resolve()
    candidate_manifest = read_json(candidate_root / "manifest.json")
    novelty = read_json(args.novelty_gate)
    teacher = episode_map(args.teacher_episodes)
    student = episode_map(args.student_episodes)
    if candidate_manifest.get("status") != "CANDIDATE_AND_NOVELTY_PROBE_PASS":
        raise RuntimeError("OPD candidate pool has not passed its data gate")
    if (
        candidate_manifest.get("source", {}).get("validation_read") is not False
        or candidate_manifest.get("source", {}).get("protocol_holdout_read")
        is not False
    ):
        raise RuntimeError("OPD candidate pool accessed a prohibited split")
    if novelty.get("status") != "PASS_TEACHER_NOVELTY":
        raise RuntimeError("teacher novelty gate is not passing")
    if set(teacher) != set(student) or len(teacher) != int(novelty["tasks"]):
        raise RuntimeError("teacher/student novelty episodes do not match")
    if any(
        row.get("status") != "SCORED" for row in [*teacher.values(), *student.values()]
    ):
        raise RuntimeError(
            "teacher-aligned selection contains infrastructure exclusions"
        )
    if (
        sha256(args.teacher_episodes) != novelty["lineage"]["teacher_episodes_sha256"]
        or sha256(args.student_episodes)
        != novelty["lineage"]["student_episodes_sha256"]
    ):
        raise RuntimeError("novelty gate episode lineage drift")

    candidates = read_jsonl(candidate_root / "tasks/train.jsonl")
    if len(candidates) != int(candidate_manifest["candidate_rows"]):
        raise RuntimeError("OPD candidate task count drift")
    candidate_verifiers = candidate_root / "verifiers/train.jsonl"
    if (
        sha256(candidate_root / "tasks/train.jsonl")
        != candidate_manifest["lineage"]["candidate_tasks_sha256"]
        or sha256(candidate_verifiers)
        != candidate_manifest["lineage"]["candidate_verifiers_sha256"]
    ):
        raise RuntimeError("OPD candidate task or verifier lineage drift")
    verifiers = verifier_map(candidate_verifiers)
    scores = family_scores(teacher, student)
    ranked = sorted(
        candidates,
        key=lambda task: task_priority(
            task,
            teacher=teacher,
            student=student,
            family=scores,
            seed=args.seed,
        ),
    )

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    group_counts: Counter[str] = Counter()
    for task in ranked:
        group = str(task["metadata"]["source_group_id"])
        if group_counts[group] >= args.max_per_source_group:
            continue
        selected.append(task)
        selected_ids.add(str(task["task_id"]))
        group_counts[group] += 1
        if len(selected) == args.train_size:
            break
    if len(selected) != args.train_size:
        raise RuntimeError(
            f"only {len(selected)} OPD train tasks survived source-group caps"
        )

    train_groups = {str(task["metadata"]["source_group_id"]) for task in selected}
    dev: list[dict[str, Any]] = []
    dev_groups: set[str] = set()
    for task in reversed(ranked):
        task_id = str(task["task_id"])
        group = str(task["metadata"]["source_group_id"])
        if task_id in selected_ids or group in train_groups or group in dev_groups:
            continue
        dev.append(task)
        dev_groups.add(group)
        if len(dev) == args.dev_size:
            break
    if len(dev) != args.dev_size:
        raise RuntimeError("insufficient group-isolated OPD training-dev tasks")

    output = args.output.resolve()
    staging = output.with_name(output.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    (staging / "tasks").mkdir(parents=True)
    (staging / "environments").mkdir()
    (staging / "verifiers").mkdir()
    write_jsonl(staging / "tasks/train.jsonl", selected)
    write_jsonl(staging / "tasks/validation.jsonl", dev)
    for task in [*selected, *dev]:
        environment_id = str(task["environment_id"])
        verifier_id = str(task["metadata"]["verifier_id"])
        verifier = verifiers.get(str(task["task_id"]))
        if verifier is None or str(verifier.get("verifier_id")) != verifier_id:
            raise RuntimeError(f"missing or mismatched verifier for {task['task_id']}")
        copy_artifact(
            candidate_root / "environments" / f"{environment_id}.json",
            staging / "environments" / f"{environment_id}.json",
        )
        write_json(staging / "verifiers" / f"{verifier_id}.json", verifier)
    DatasetDict(
        {
            "train": Dataset.from_list([dataset_row(task) for task in selected]),
            "validation": Dataset.from_list([dataset_row(task) for task in dev]),
        }
    ).save_to_disk(staging / "hf_dataset")

    selected_probe = sum(str(task["task_id"]) in teacher for task in selected)
    teacher_only_selected = sum(
        str(task["task_id"]) in teacher
        and teacher[str(task["task_id"])]["strict_success"]
        and not student[str(task["task_id"])]["strict_success"]
        for task in selected
    )
    manifest = {
        "schema_version": "studyhub.opd-prompt-pool.v1",
        "status": "PASS_TEACHER_ALIGNED_SELECTION",
        "seed": args.seed,
        "train_rows": len(selected),
        "validation_rows": len(dev),
        "train_family_counts": dict(
            sorted(Counter(task["metadata"]["family"] for task in selected).items())
        ),
        "validation_family_counts": dict(
            sorted(Counter(task["metadata"]["family"] for task in dev).items())
        ),
        "train_budget_counts": dict(
            sorted(Counter(task["budget_tier"] for task in selected).items())
        ),
        "unique_train_source_groups": len(train_groups),
        "unique_validation_source_groups": len(dev_groups),
        "train_validation_group_overlap": 0,
        "novelty_probe_tasks_in_train": selected_probe,
        "directly_observed_teacher_only_tasks_in_train": teacher_only_selected,
        "family_novelty_scores": scores,
        "selection_order": [
            "teacher_pass_student_fail",
            "teacher_pass_positive_diagnostic_delta",
            "positive_per_task_delta",
            "positive_family_novelty",
            "deterministic_hash",
        ],
        "sealed_used": False,
        "validation_or_protocol_holdout_used": False,
        "lineage": {
            "candidate_manifest_sha256": sha256(candidate_root / "manifest.json"),
            "candidate_tasks_sha256": sha256(candidate_root / "tasks/train.jsonl"),
            "teacher_episodes_sha256": sha256(args.teacher_episodes),
            "student_episodes_sha256": sha256(args.student_episodes),
            "novelty_gate_sha256": sha256(args.novelty_gate),
            "train_tasks_sha256": sha256(staging / "tasks/train.jsonl"),
            "validation_tasks_sha256": sha256(staging / "tasks/validation.jsonl"),
        },
    }
    write_json(staging / "manifest.json", manifest)
    shutil.rmtree(output, ignore_errors=True)
    os.replace(staging, output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
