#!/usr/bin/env python3
"""Package an existing OPD prompt pool for the Hermes rollout runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def inventory_sha256(paths: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def package_pool(root: Path) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = root / "manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("status") != "PASS_TEACHER_ALIGNED_SELECTION":
        raise RuntimeError("OPD prompt pool has not passed teacher-aligned selection")

    tasks_by_split = {
        "train": read_jsonl(root / "tasks/train.jsonl"),
        "validation": read_jsonl(root / "tasks/validation.jsonl"),
    }
    expected_counts = {
        "train": int(manifest["train_rows"]),
        "validation": int(manifest["validation_rows"]),
    }
    if {split: len(rows) for split, rows in tasks_by_split.items()} != expected_counts:
        raise RuntimeError("OPD task split counts differ from the frozen manifest")

    seen_tasks: set[str] = set()
    seen_verifiers: set[str] = set()
    environment_paths: set[Path] = set()
    verifiers_by_split: dict[str, list[dict[str, Any]]] = {}
    for split, tasks in tasks_by_split.items():
        rows: list[dict[str, Any]] = []
        for task in tasks:
            task_id = str(task["task_id"])
            verifier_id = str(task["metadata"]["verifier_id"])
            environment_id = str(task["environment_id"])
            if task_id in seen_tasks or verifier_id in seen_verifiers:
                raise RuntimeError(f"duplicate OPD task/verifier identity: {task_id}")
            verifier_path = root / "verifiers" / f"{verifier_id}.json"
            environment_path = root / "environments" / f"{environment_id}.json"
            if not verifier_path.is_file() or not environment_path.is_file():
                raise FileNotFoundError(
                    f"missing OPD runtime fixture for task={task_id}, "
                    f"verifier={verifier_path}, environment={environment_path}"
                )
            verifier = read_json(verifier_path)
            environment = read_json(environment_path)
            if (
                str(verifier.get("verifier_id")) != verifier_id
                or str(verifier.get("task_id")) != task_id
                or str(environment.get("task_id")) != task_id
            ):
                raise RuntimeError(f"OPD runtime fixture identity mismatch: {task_id}")
            rows.append(verifier)
            seen_tasks.add(task_id)
            seen_verifiers.add(verifier_id)
            environment_paths.add(environment_path)
        verifiers_by_split[split] = rows

    train_verifiers = root / "verifiers/train.jsonl"
    validation_verifiers = root / "verifiers/validation.jsonl"
    write_jsonl(train_verifiers, verifiers_by_split["train"])
    write_jsonl(validation_verifiers, verifiers_by_split["validation"])

    original_manifest_sha = sha256(manifest_path)
    lineage = manifest.setdefault("lineage", {})
    lineage.setdefault("pre_runtime_packaging_manifest_sha256", original_manifest_sha)
    lineage.update(
        {
            "train_verifiers_sha256": sha256(train_verifiers),
            "validation_verifiers_sha256": sha256(validation_verifiers),
            "environment_inventory_sha256": inventory_sha256(list(environment_paths), root),
        }
    )
    manifest["runtime_packaging"] = {
        "format": "split-verifier-jsonl-plus-per-task-environment-json",
        "train_verifiers": len(verifiers_by_split["train"]),
        "validation_verifiers": len(verifiers_by_split["validation"]),
        "environments": len(environment_paths),
        "task_verifier_environment_mapping_complete": True,
    }
    write_json(manifest_path, manifest)
    return {
        "status": "PASS_OPD_RUNTIME_PACKAGING",
        "root": str(root),
        "train_verifiers": len(verifiers_by_split["train"]),
        "validation_verifiers": len(verifiers_by_split["validation"]),
        "environments": len(environment_paths),
        "manifest_sha256": sha256(manifest_path),
        "train_verifiers_sha256": sha256(train_verifiers),
        "validation_verifiers_sha256": sha256(validation_verifiers),
        "environment_inventory_sha256": lineage["environment_inventory_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package_pool(args.root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
