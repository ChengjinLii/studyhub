#!/usr/bin/env python3
"""Compare frozen T9 and M2 on exactly the same 500 training-only prompts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher-episodes", type=Path, required=True)
    parser.add_argument("--student-episodes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-tasks", type=int, default=500)
    parser.add_argument("--minimum-teacher-only", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    teacher = {str(row["task_id"]): row for row in read_jsonl(args.teacher_episodes)}
    student = {str(row["task_id"]): row for row in read_jsonl(args.student_episodes)}
    if len(teacher) != args.expected_tasks or len(student) != args.expected_tasks:
        raise RuntimeError(
            f"novelty gate requires {args.expected_tasks} unique tasks per model: "
            f"teacher={len(teacher)} student={len(student)}"
        )
    if set(teacher) != set(student):
        raise RuntimeError("teacher and student novelty task IDs differ")
    infra = [
        [task_id, teacher[task_id]["status"], student[task_id]["status"]]
        for task_id in sorted(teacher)
        if teacher[task_id]["status"] != "SCORED"
        or student[task_id]["status"] != "SCORED"
    ]
    if infra:
        raise RuntimeError(
            f"novelty gate contains infrastructure exclusions: {infra[:5]}"
        )

    teacher_success = {
        task_id for task_id, row in teacher.items() if row["strict_success"]
    }
    student_success = {
        task_id for task_id, row in student.items() if row["strict_success"]
    }
    teacher_only = teacher_success - student_success
    student_only = student_success - teacher_success
    differences = {
        task_id: round(
            float(teacher[task_id]["diagnostic_score"])
            - float(student[task_id]["diagnostic_score"]),
            6,
        )
        for task_id in teacher
    }
    gate_pass = (
        len(teacher_success) > len(student_success)
        and len(teacher_only) >= args.minimum_teacher_only
    )
    by_family: dict[str, dict[str, Any]] = {}
    for family in sorted({str(row["family"]) for row in teacher.values()}):
        task_ids = [
            task_id for task_id, row in teacher.items() if row["family"] == family
        ]
        by_family[family] = {
            "tasks": len(task_ids),
            "teacher_successes": sum(
                task_id in teacher_success for task_id in task_ids
            ),
            "student_successes": sum(
                task_id in student_success for task_id in task_ids
            ),
            "teacher_only_successes": sum(
                task_id in teacher_only for task_id in task_ids
            ),
            "mean_diagnostic_delta": round(
                sum(differences[task_id] for task_id in task_ids)
                / max(len(task_ids), 1),
                6,
            ),
        }
    ranked = sorted(
        teacher,
        key=lambda task_id: (
            task_id not in teacher_only,
            not bool(teacher[task_id]["strict_success"]),
            -differences[task_id],
            task_id,
        ),
    )
    result = {
        "schema_version": "studyhub.opd-teacher-novelty-gate.v1",
        "status": (
            "PASS_TEACHER_NOVELTY" if gate_pass else "BLOCKED_OPD_NO_TEACHER_NOVELTY"
        ),
        "tasks": len(teacher),
        "teacher_successes": len(teacher_success),
        "student_successes": len(student_success),
        "teacher_only_successes": len(teacher_only),
        "student_only_successes": len(student_only),
        "both_successes": len(teacher_success & student_success),
        "neither_successes": len(teacher) - len(teacher_success | student_success),
        "teacher_mean_diagnostic": round(
            sum(float(row["diagnostic_score"]) for row in teacher.values())
            / len(teacher),
            6,
        ),
        "student_mean_diagnostic": round(
            sum(float(row["diagnostic_score"]) for row in student.values())
            / len(student),
            6,
        ),
        "teacher_mean_tool_validity": round(
            sum(float(row["tool_validity"]) for row in teacher.values()) / len(teacher),
            6,
        ),
        "student_mean_tool_validity": round(
            sum(float(row["tool_validity"]) for row in student.values()) / len(student),
            6,
        ),
        "family_slices": by_family,
        "teacher_only_task_ids": sorted(teacher_only),
        "student_only_task_ids": sorted(student_only),
        "ranked_probe_task_ids": ranked,
        "diagnostic_delta_signs": dict(
            Counter(
                "positive" if value > 0 else "negative" if value < 0 else "zero"
                for value in differences.values()
            )
        ),
        "contract": {
            "teacher_success_must_exceed_student": True,
            "minimum_teacher_only_successes": args.minimum_teacher_only,
            "same_task_ids": True,
            "post_hoc_threshold_change": False,
        },
        "lineage": {
            "teacher_episodes_sha256": sha256(args.teacher_episodes),
            "student_episodes_sha256": sha256(args.student_episodes),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if gate_pass else 3


if __name__ == "__main__":
    raise SystemExit(main())
