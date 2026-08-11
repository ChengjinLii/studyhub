"""Export the validated router dataset to an isolated LLaMA-Factory data dir."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .build_validation_dataset import (
    DEFAULT_CHUNKS_PATH,
    DEFAULT_MATERIALS_PATH,
    DEFAULT_OUTPUT_DIR,
)
from .spec import audit_datasets, load_jsonl, sha256_file

DEFAULT_SOURCE = DEFAULT_OUTPUT_DIR / "router_tool_2b.jsonl"
DEFAULT_DATASET_DIR = DEFAULT_OUTPUT_DIR / "llamafactory"
DATASET_NAMES = {
    "train": "studyhub_router_2b_train",
    "validation": "studyhub_router_2b_validation",
    "test": "studyhub_router_2b_test",
}


def _dataset_names(prefix: str) -> dict[str, str]:
    return {
        split: f"{prefix}_{split}"
        for split in ("train", "validation", "test")
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def export_llamafactory_dataset(
    *,
    source_path: Path = DEFAULT_SOURCE,
    dataset_dir: Path = DEFAULT_DATASET_DIR,
    materials_path: Path = DEFAULT_MATERIALS_PATH,
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
    expected_profile_count: int = 500,
    expected_split_counts: dict[str, int] | None = None,
    target_profile: str = "router_tool_2b",
    file_prefix: str = "router_tool_2b",
    dataset_name_prefix: str = "studyhub_router_2b",
) -> dict[str, Any]:
    expected_splits = expected_split_counts or {
        "train": 400,
        "validation": 50,
        "test": 50,
    }
    audit = audit_datasets(
        [source_path],
        materials_path=materials_path,
        chunks_path=chunks_path,
        expected_profile_counts={target_profile: expected_profile_count},
        expected_split_counts={target_profile: expected_splits},
    )
    if not audit.passed:
        raise ValueError("source dataset failed validation: " + "; ".join(audit.errors[:10]))

    by_split: dict[str, list[dict[str, Any]]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    family_counts: dict[str, Counter[str]] = {
        split: Counter() for split in by_split
    }
    for record in load_jsonl(source_path):
        split = str(record["split"])
        messages = [
            {"role": message["role"], "content": message["content"]}
            for message in record["messages"]
        ]
        by_split[split].append(
            {
                "messages": messages,
                "example_id": record["example_id"],
                "task_family": record["task_family"],
            }
        )
        family_counts[split][str(record["task_family"])] += 1

    dataset_info: dict[str, Any] = {}
    files: dict[str, Any] = {}
    dataset_names = (
        DATASET_NAMES
        if dataset_name_prefix == "studyhub_router_2b"
        else _dataset_names(dataset_name_prefix)
    )
    for split, rows in by_split.items():
        filename = f"{file_prefix}_{split}.jsonl"
        path = dataset_dir / filename
        _write_jsonl(path, rows)
        dataset_info[dataset_names[split]] = {
            "file_name": filename,
            "formatting": "sharegpt",
            "columns": {"messages": "messages"},
            "tags": {
                "role_tag": "role",
                "content_tag": "content",
                "user_tag": "user",
                "assistant_tag": "assistant",
                "system_tag": "system",
            },
        }
        files[filename] = {
            "records": len(rows),
            "sha256": sha256_file(path),
        }

    dataset_info_path = dataset_dir / "dataset_info.json"
    dataset_info_path.write_text(
        json.dumps(dataset_info, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "source": str(source_path),
        "source_sha256": sha256_file(source_path),
        "dataset_info_sha256": sha256_file(dataset_info_path),
        "counts": {split: len(rows) for split, rows in by_split.items()},
        "family_counts": {
            split: dict(sorted(counts.items()))
            for split, counts in family_counts.items()
        },
        "files": files,
        "assistant_only_loss": True,
        "template": "qwen3_5_nothink",
        "target_profile": target_profile,
        "dataset_names": dataset_names,
    }
    (dataset_dir / "export_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--materials", type=Path, default=DEFAULT_MATERIALS_PATH)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--expected-count", type=int, default=500)
    parser.add_argument("--expected-train", type=int, default=400)
    parser.add_argument("--expected-validation", type=int, default=50)
    parser.add_argument("--expected-test", type=int, default=50)
    parser.add_argument("--target-profile", default="router_tool_2b")
    parser.add_argument("--file-prefix", default="router_tool_2b")
    parser.add_argument("--dataset-name-prefix", default="studyhub_router_2b")
    args = parser.parse_args()
    manifest = export_llamafactory_dataset(
        source_path=args.source,
        dataset_dir=args.dataset_dir,
        materials_path=args.materials,
        chunks_path=args.chunks,
        expected_profile_count=args.expected_count,
        expected_split_counts={
            "train": args.expected_train,
            "validation": args.expected_validation,
            "test": args.expected_test,
        },
        target_profile=args.target_profile,
        file_prefix=args.file_prefix,
        dataset_name_prefix=args.dataset_name_prefix,
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
