#!/usr/bin/env python3
"""Compile canonical chat records into AReaL input_ids and loss_mask."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SOURCE_QUOTAS = {
    "toolace": 300,
    "hermes_function_calling": 300,
    "2wiki": 900,
    "qasper": 600,
    "coig_exam": 900,
}
SPLIT_RATIOS = {"train": 0.85, "validation": 0.10, "test": 0.05}


def stable_key(value: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def split_targets(quota: int) -> dict[str, int]:
    train = int(quota * SPLIT_RATIOS["train"])
    validation = int(quota * SPLIT_RATIOS["validation"])
    return {"train": train, "validation": validation, "test": quota - train - validation}


def split_for_group(source: str, group_id: str) -> str:
    bucket = int(stable_key(f"{source}:{group_id}", "group-split")[:8], 16) % 10_000
    if bucket < 8_500:
        return "train"
    if bucket < 9_500:
        return "validation"
    return "test"


def assistant_loss_mask(tokenizer, messages: list[dict[str, str]]) -> tuple[list[int], list[int], str]:
    rendered = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
        enable_thinking=False,
    )
    input_ids = tokenizer(rendered, add_special_tokens=False)["input_ids"]
    im_start = tokenizer.convert_tokens_to_ids("<|im_start|>")
    im_end = tokenizer.convert_tokens_to_ids("<|im_end|>")
    header = tokenizer.encode("assistant\n", add_special_tokens=False)
    if im_start is None or im_end is None or im_start < 0 or im_end < 0:
        raise RuntimeError("Qwen chat boundary tokens are unavailable")
    loss_mask = [0] * len(input_ids)
    blocks = 0
    index = 0
    while index < len(input_ids):
        if input_ids[index] != im_start or input_ids[index + 1 : index + 1 + len(header)] != header:
            index += 1
            continue
        content_start = index + 1 + len(header)
        try:
            content_end = input_ids.index(im_end, content_start)
        except ValueError as exc:
            raise RuntimeError("Unterminated assistant block") from exc
        for position in range(content_start, content_end + 1):
            loss_mask[position] = 1
        blocks += 1
        index = content_end + 1
    expected_blocks = sum(item["role"] == "assistant" for item in messages)
    if blocks != expected_blocks or not any(loss_mask):
        raise RuntimeError(f"Assistant mask mismatch: expected {expected_blocks}, found {blocks}")
    return input_ids, loss_mask, rendered


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    return sorted(values)[min(len(values) - 1, math.ceil(len(values) * fraction) - 1)]


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input", type=Path, default=project / "datasets/interim/open_sft_bootstrap_v2/candidates.jsonl"
    )
    parser.add_argument("--model", type=Path, default=project.parent / "models/P0/Qwen3.5-2B")
    parser.add_argument(
        "--output", type=Path, default=project / "datasets/processed/open_sft_bootstrap_v2"
    )
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from datasets import Dataset, DatasetDict
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    compiled = defaultdict(list)
    dropped = Counter()
    with args.input.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            source = row["source_dataset"]
            if source not in SOURCE_QUOTAS:
                dropped["unknown_source"] += 1
                continue
            try:
                input_ids, loss_mask, _ = assistant_loss_mask(tokenizer, row["messages"])
            except Exception:
                dropped[f"{source}:mask_error"] += 1
                continue
            if len(input_ids) > args.max_length:
                dropped[f"{source}:too_long"] += 1
                continue
            row["input_ids"] = input_ids
            row["loss_mask"] = loss_mask
            compiled[source].append(row)

    split_rows: dict[str, list[dict[str, Any]]] = {"train": [], "validation": [], "test": []}
    source_split_counts: dict[str, dict[str, int]] = {}
    for source, quota in SOURCE_QUOTAS.items():
        pools: dict[str, list[dict[str, Any]]] = {"train": [], "validation": [], "test": []}
        for row in compiled[source]:
            split = split_for_group(source, row.get("group_id", row["source_id"]))
            pools[split].append(row)
        source_split_counts[source] = {}
        for split, target in split_targets(quota).items():
            rows = sorted(pools[split], key=lambda row: stable_key(row["id"], f"select:{split}"))
            if len(rows) < target:
                raise RuntimeError(
                    f"Only {len(rows)} tokenized rows for {source}/{split}; need {target}"
                )
            selected = rows[:target]
            split_rows[split].extend(selected)
            source_split_counts[source][split] = len(selected)

    group_sets = {
        split: {(row["source_dataset"], row.get("group_id", row["source_id"])) for row in rows}
        for split, rows in split_rows.items()
    }
    group_overlap = {
        "train_validation": len(group_sets["train"] & group_sets["validation"]),
        "train_test": len(group_sets["train"] & group_sets["test"]),
        "validation_test": len(group_sets["validation"] & group_sets["test"]),
    }
    if any(group_overlap.values()):
        raise RuntimeError(f"Group leakage detected: {group_overlap}")

    if args.output.exists():
        if not args.overwrite:
            raise FileExistsError(f"Output exists; pass --overwrite: {args.output}")
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)
    hf_splits = {}
    metadata_dir = args.output / "metadata"
    metadata_dir.mkdir()
    lengths = []
    trained_tokens = 0
    all_tokens = 0
    for split, rows in split_rows.items():
        rows.sort(key=lambda row: stable_key(row["id"], f"order:{split}"))
        hf_splits[split] = Dataset.from_list(
            [{"input_ids": row["input_ids"], "loss_mask": row["loss_mask"]} for row in rows]
        )
        with (metadata_dir / f"{split}.jsonl").open("w", encoding="utf-8") as stream:
            for row in rows:
                metadata = {key: value for key, value in row.items() if key not in {"input_ids", "loss_mask"}}
                stream.write(json.dumps(metadata, ensure_ascii=False) + "\n")
                lengths.append(len(row["input_ids"]))
                trained_tokens += sum(row["loss_mask"])
                all_tokens += len(row["input_ids"])
    dataset_path = args.output / "hf_dataset"
    DatasetDict(hf_splits).save_to_disk(dataset_path)
    manifest = {
        "schema_version": "studyhub.areal-sft-dataset-manifest.v2",
        "model_tokenizer": str(args.model.resolve()),
        "max_length": args.max_length,
        "source_quotas": SOURCE_QUOTAS,
        "source_split_counts": source_split_counts,
        "split_counts": {key: len(value) for key, value in split_rows.items()},
        "split_strategy": "deterministic source-stratified group split (85/10/5)",
        "group_overlap": group_overlap,
        "drop_counts": dict(sorted(dropped.items())),
        "token_length": {
            "min": min(lengths),
            "p50": percentile(lengths, 0.50),
            "p95": percentile(lengths, 0.95),
            "max": max(lengths),
        },
        "assistant_token_fraction": round(trained_tokens / all_tokens, 6),
        "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
        "candidate_manifest": str(args.input.with_suffix(".manifest.json").resolve()),
        "candidate_manifest_sha256": hashlib.sha256(
            args.input.with_suffix(".manifest.json").read_bytes()
        ).hexdigest(),
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
