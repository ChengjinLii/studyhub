#!/usr/bin/env python3
"""Package reviewed v2.1 Development/Calibration candidates, never Sealed data."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ALLOWED_SPLITS = {"development", "calibration"}
FORBIDDEN_TASK_KEYS = {
    "gold_answer",
    "gold_path",
    "gold_query",
    "hidden_grader",
    "oracle_trajectory",
    "supporting_facts",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"expected object at {path}:{line_number}")
        rows.append(value)
    return rows


def build_public_candidates(
    source_catalog_path: Path,
    task_candidates_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sources = read_jsonl(source_catalog_path)
    tasks = read_jsonl(task_candidates_path)
    source_by_id: dict[str, dict[str, Any]] = {}
    for source in sources:
        source_id = str(source["source_group_id"])
        if source_id in source_by_id:
            raise RuntimeError(f"duplicate source group: {source_id}")
        if source.get("license_status") != "verified":
            raise RuntimeError(f"source license is not verified: {source_id}")
        if source.get("training_overlap") is not False:
            raise RuntimeError(f"source training isolation is not proven: {source_id}")
        if source.get("independence_review") != "PASS":
            raise RuntimeError(f"source independence review is not PASS: {source_id}")
        if source.get("split") not in ALLOWED_SPLITS:
            raise RuntimeError(f"public builder refuses split: {source.get('split')}")
        source_by_id[source_id] = source

    task_ids: set[str] = set()
    source_counts: Counter[str] = Counter()
    output = []
    for task in tasks:
        task_id = str(task["task_id"])
        split = str(task["split"])
        source_id = str(task["source_group_id"])
        if task_id in task_ids:
            raise RuntimeError(f"duplicate task ID: {task_id}")
        if split not in ALLOWED_SPLITS:
            raise RuntimeError(f"public builder refuses split: {split}")
        if source_id not in source_by_id:
            raise RuntimeError(f"unknown reviewed source group: {source_id}")
        if source_by_id[source_id]["split"] != split:
            raise RuntimeError(f"task/source split mismatch: {task_id}")
        forbidden = sorted(FORBIDDEN_TASK_KEYS.intersection(task))
        if forbidden:
            raise RuntimeError(f"public task contains hidden/oracle fields: {task_id}: {forbidden}")
        if task.get("independent_semantic_review") != "PASS":
            raise RuntimeError(f"task semantic review is not PASS: {task_id}")
        task_ids.add(task_id)
        source_counts[source_id] += 1
        output.append(task)

    over_cap = sorted(source_id for source_id, count in source_counts.items() if count > 4)
    if over_cap:
        raise RuntimeError(f"source groups exceed four-row cap: {over_cap}")
    manifest = {
        "schema_version": "studyhub.agentbench-v2.1-public-candidates.v1",
        "status": "PUBLIC_CANDIDATES_BUILT_NOT_FROZEN",
        "rows": len(output),
        "split_counts": dict(sorted(Counter(str(row["split"]) for row in output).items())),
        "source_groups": len(source_counts),
        "maximum_rows_per_source_group": max(source_counts.values(), default=0),
        "sealed_accessed": False,
        "model_evaluation_allowed": False,
        "inputs": {
            "source_catalog_sha256": sha256(source_catalog_path),
            "task_candidates_sha256": sha256(task_candidates_path),
        },
    }
    return output, manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-catalog", type=Path, required=True)
    parser.add_argument("--task-candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows, manifest = build_public_candidates(args.source_catalog, args.task_candidates)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": manifest["status"], "rows": manifest["rows"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
