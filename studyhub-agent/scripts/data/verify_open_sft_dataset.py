#!/usr/bin/env python3
"""Audit a compiled StudyHub open SFT dataset before GPU training."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[int], fraction: float) -> int:
    return sorted(values)[min(len(values) - 1, math.ceil(len(values) * fraction) - 1)]


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset", type=Path, default=project / "datasets/processed/open_sft_bootstrap_v2"
    )
    parser.add_argument(
        "--output", type=Path, default=project / "artifacts/areal/dataset-audit-v2.json"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from datasets import load_from_disk

    manifest_path = args.dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset = load_from_disk(args.dataset / "hf_dataset")
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    candidate_manifest = Path(manifest["candidate_manifest"])
    candidate_file = candidate_manifest.with_name("candidates.jsonl")
    check(candidate_manifest.is_file(), "candidate manifest is missing")
    check(candidate_file.is_file(), "candidate JSONL is missing")
    if candidate_manifest.is_file():
        check(
            sha256(candidate_manifest) == manifest["candidate_manifest_sha256"],
            "candidate manifest SHA-256 mismatch",
        )
    if candidate_file.is_file():
        check(sha256(candidate_file) == manifest["input_sha256"], "candidate JSONL SHA-256 mismatch")

    required_metadata = {
        "id",
        "group_id",
        "source_dataset",
        "source_id",
        "task_family",
        "license",
        "revision",
        "source_url",
        "content_sha256",
    }
    ids: set[str] = set()
    content_hashes: set[str] = set()
    group_sets: dict[str, set[tuple[str, str]]] = {}
    observed_source_counts: dict[str, dict[str, int]] = {}
    lengths: list[int] = []
    all_tokens = 0
    loss_tokens = 0
    split_details: dict[str, Any] = {}

    for split in ("train", "validation", "test"):
        metadata_path = args.dataset / "metadata" / f"{split}.jsonl"
        metadata = [json.loads(line) for line in metadata_path.read_text(encoding="utf-8").splitlines()]
        tensors = dataset[split]
        check(len(metadata) == len(tensors), f"{split}: metadata/tensor row count mismatch")
        check(len(metadata) == manifest["split_counts"][split], f"{split}: manifest row count mismatch")
        groups: set[tuple[str, str]] = set()
        source_counts: Counter[str] = Counter()
        for index, (meta, tensor) in enumerate(zip(metadata, tensors, strict=True)):
            missing = required_metadata - meta.keys()
            check(not missing, f"{split}[{index}]: missing metadata {sorted(missing)}")
            check(meta["id"] not in ids, f"duplicate id: {meta['id']}")
            check(meta["content_sha256"] not in content_hashes, f"duplicate content: {meta['id']}")
            ids.add(meta["id"])
            content_hashes.add(meta["content_sha256"])
            groups.add((meta["source_dataset"], meta["group_id"]))
            source_counts[meta["source_dataset"]] += 1

            input_ids = tensor["input_ids"]
            loss_mask = tensor["loss_mask"]
            check(len(input_ids) == len(loss_mask), f"{split}[{index}]: mask length mismatch")
            check(0 < len(input_ids) <= manifest["max_length"], f"{split}[{index}]: invalid length")
            check(set(loss_mask).issubset({0, 1}), f"{split}[{index}]: non-binary loss mask")
            check(any(loss_mask), f"{split}[{index}]: empty assistant loss mask")
            lengths.append(len(input_ids))
            all_tokens += len(input_ids)
            loss_tokens += sum(loss_mask)

        group_sets[split] = groups
        observed_source_counts[split] = dict(source_counts)
        split_details[split] = {
            "rows": len(metadata),
            "groups": len(groups),
            "source_counts": dict(sorted(source_counts.items())),
        }

    overlap = {
        "train_validation": len(group_sets["train"] & group_sets["validation"]),
        "train_test": len(group_sets["train"] & group_sets["test"]),
        "validation_test": len(group_sets["validation"] & group_sets["test"]),
    }
    check(not any(overlap.values()), f"cross-split group leakage: {overlap}")
    for source, expected in manifest["source_split_counts"].items():
        for split, count in expected.items():
            check(
                observed_source_counts[split].get(source, 0) == count,
                f"{source}/{split}: source quota mismatch",
            )

    token_stats = {
        "min": min(lengths),
        "p50": percentile(lengths, 0.50),
        "p95": percentile(lengths, 0.95),
        "max": max(lengths),
        "all_tokens": all_tokens,
        "loss_tokens": loss_tokens,
        "assistant_token_fraction": round(loss_tokens / all_tokens, 6),
    }
    for key in ("min", "p50", "p95", "max"):
        check(token_stats[key] == manifest["token_length"][key], f"token statistic mismatch: {key}")
    check(
        token_stats["assistant_token_fraction"] == manifest["assistant_token_fraction"],
        "assistant token fraction mismatch",
    )

    result = {
        "schema_version": "studyhub.open-sft-dataset-audit.v1",
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": str(args.dataset.resolve()),
        "dataset_manifest_sha256": sha256(manifest_path),
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "split_details": split_details,
        "group_overlap": overlap,
        "unique_ids": len(ids),
        "unique_content_hashes": len(content_hashes),
        "token_stats": token_stats,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
