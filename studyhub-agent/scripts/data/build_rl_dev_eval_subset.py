#!/usr/bin/env python3
"""Build a deterministic, stratified RL development-evaluation subset."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from datasets import DatasetDict, load_from_disk


TARGETS = {
    ("function_calling", "toolace", "medium"): 3,
    ("function_calling", "toolace", "hard"): 3,
    ("function_calling", "hermes_function_calling", "medium"): 3,
    ("function_calling", "hermes_function_calling", "hard"): 3,
    ("search_multihop", "2wiki", "medium"): 8,
    ("search_multihop", "2wiki", "hard"): 4,
    ("evidence_grounding", "qasper", "hard"): 8,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_rank(seed: int, task_id: str) -> str:
    return hashlib.sha256(f"{seed}:{task_id}".encode()).hexdigest()


def _bucket(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["family"]),
        str(row["metadata"]["source_dataset"]),
        str(row["difficulty"]),
    )


def build_subset(source: Path, output: Path, seed: int) -> dict[str, Any]:
    source = source.resolve()
    output = output.resolve()
    dataset = load_from_disk(str(source / "hf_dataset"))
    validation = dataset["validation"]
    train_group_ids = {str(row["metadata"]["group_id"]) for row in dataset["train"]}

    selected_indices: list[int] = []
    realized: Counter[tuple[str, str, str]] = Counter()
    for bucket, count in TARGETS.items():
        candidates = [
            index for index, row in enumerate(validation) if _bucket(row) == bucket
        ]
        candidates.sort(key=lambda index: _stable_rank(seed, validation[index]["task_id"]))
        if len(candidates) < count:
            raise RuntimeError(f"insufficient validation tasks for {bucket}: {len(candidates)} < {count}")
        chosen = candidates[:count]
        selected_indices.extend(chosen)
        realized[bucket] += len(chosen)

    selected_indices.sort(
        key=lambda index: (
            *_bucket(validation[index]),
            _stable_rank(seed, validation[index]["task_id"]),
        )
    )
    selected = validation.select(selected_indices)
    task_ids = [str(row["task_id"]) for row in selected]
    if len(task_ids) != len(set(task_ids)):
        raise RuntimeError("duplicate task IDs in evaluation subset")
    selected_group_ids = [str(row["metadata"]["group_id"]) for row in selected]
    overlap = sorted(set(selected_group_ids) & train_group_ids)
    if overlap:
        raise RuntimeError(f"evaluation lineage overlaps RL train: {overlap[:3]}")
    if any(row.get("verifier") for row in selected):
        raise RuntimeError("public evaluation tasks expose hidden verifier fields")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    DatasetDict({"validation": selected}).save_to_disk(str(output / "hf_dataset"))
    task_path = output / "tasks.jsonl"
    task_path.write_text(
        "".join(
            json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n"
            for row in selected
        ),
        encoding="utf-8",
    )
    source_manifest = source / "manifest.json"
    manifest = {
        "schema_version": "studyhub.rl-dev-eval-subset.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seed": seed,
        "role": "development evaluation; not the sealed final test",
        "source_root": str(source),
        "source_manifest_sha256": _sha256(source_manifest),
        "task_count": len(selected),
        "task_ids": task_ids,
        "task_jsonl_sha256": _sha256(task_path),
        "target_buckets": {"|".join(key): value for key, value in TARGETS.items()},
        "realized_buckets": {"|".join(key): value for key, value in sorted(realized.items())},
        "family_counts": dict(Counter(str(row["family"]) for row in selected)),
        "source_counts": dict(
            Counter(str(row["metadata"]["source_dataset"]) for row in selected)
        ),
        "difficulty_counts": dict(Counter(str(row["difficulty"]) for row in selected)),
        "rl_train_group_overlap": 0,
        "public_verifier_fields_empty": True,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("datasets/processed/open_agent_rl_v1"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("datasets/processed/open_agent_rl_dev_eval32_v1"),
    )
    parser.add_argument("--seed", type=int, default=6209)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(json.dumps(build_subset(args.source, args.output, args.seed), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
