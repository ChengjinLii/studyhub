#!/usr/bin/env python3
"""Compile v3 runtime trajectories into AReaL SFT tensors."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]


def assistant_loss_mask(
    tokenizer: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> tuple[list[int], list[int], str]:
    rendered = tokenizer.apply_chat_template(
        messages,
        tools=tools or None,
        tokenize=False,
        add_generation_prompt=False,
        enable_thinking=False,
    )
    input_ids = tokenizer(rendered, add_special_tokens=False)["input_ids"]
    im_start = tokenizer.convert_tokens_to_ids("<|im_start|>")
    im_end = tokenizer.convert_tokens_to_ids("<|im_end|>")
    assistant_header = tokenizer.encode("assistant\n", add_special_tokens=False)
    if not isinstance(im_start, int) or not isinstance(im_end, int) or im_start < 0 or im_end < 0:
        raise RuntimeError("Qwen chat boundary tokens are unavailable")
    loss_mask = [0] * len(input_ids)
    blocks = 0
    index = 0
    while index < len(input_ids):
        if input_ids[index] != im_start or input_ids[index + 1 : index + 1 + len(assistant_header)] != assistant_header:
            index += 1
            continue
        content_start = index + 1 + len(assistant_header)
        try:
            content_end = input_ids.index(im_end, content_start)
        except ValueError as exc:
            raise RuntimeError("unterminated assistant block") from exc
        for position in range(content_start, content_end + 1):
            loss_mask[position] = 1
        blocks += 1
        index = content_end + 1
    expected = sum(message.get("role") == "assistant" for message in messages)
    if blocks != expected or not any(loss_mask):
        raise RuntimeError(f"assistant mask mismatch: expected {expected}, found {blocks}")
    return input_ids, loss_mask, rendered


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=project / "datasets/interim/runtime_sft_v3/selected.jsonl")
    parser.add_argument("--model", type=Path, default=project.parent / "models/P1/Qwen3.5-9B")
    parser.add_argument("--output", type=Path, default=project / "datasets/processed/runtime_sft_v3_qwen35_9b")
    parser.add_argument("--max-length", type=int, default=8192)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from transformers import AutoTokenizer

    from datasets import Dataset, DatasetDict

    selected_manifest_path = args.input.with_suffix(".manifest.json")
    selected_manifest = json.loads(selected_manifest_path.read_text(encoding="utf-8"))
    if selected_manifest.get("status") != "SELECTED_PENDING_TOKENIZATION":
        raise RuntimeError("selected trajectory manifest is not ready for tokenization")
    if selected_manifest.get("output_sha256") != sha256(args.input):
        raise RuntimeError("selected trajectory file does not match its manifest")
    benchmark_lock = selected_manifest.get("benchmark_lock")
    if not isinstance(benchmark_lock, dict) or benchmark_lock.get("benchmark_version") != "studyhub-agentbench-v2":
        raise RuntimeError("selected trajectories are not bound to frozen Benchmark v2")

    tokenizer = AutoTokenizer.from_pretrained(
        args.model,
        trust_remote_code=True,
        local_files_only=True,
    )
    split_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    drops: Counter[str] = Counter()
    source_counts: dict[str, Counter[str]] = defaultdict(Counter)
    source_token_counts: Counter[str] = Counter()
    source_loss_token_counts: Counter[str] = Counter()
    lengths: list[int] = []
    all_tokens = 0
    loss_tokens = 0
    with args.input.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            try:
                input_ids, loss_mask, rendered = assistant_loss_mask(
                    tokenizer,
                    row["messages"],
                    row["tools"],
                )
            except Exception as exc:  # noqa: BLE001 - preserve source-specific data failures
                drops[f"mask_error:{type(exc).__name__}"] += 1
                continue
            if len(input_ids) > args.max_length:
                drops[f"too_long:{row['source_dataset']}"] += 1
                continue
            split = str(row["split"])
            source = str(row["source_dataset"])
            row["input_ids"] = input_ids
            row["loss_mask"] = loss_mask
            row["rendered_sha256"] = hashlib.sha256(rendered.encode()).hexdigest()
            split_rows[split].append(row)
            source_counts[source][split] += 1
            source_token_counts[source] += len(input_ids)
            source_loss_token_counts[source] += sum(loss_mask)
            lengths.append(len(input_ids))
            all_tokens += len(input_ids)
            loss_tokens += sum(loss_mask)
    if drops:
        raise RuntimeError(f"v3 tokenization is fail-closed; dropped rows: {dict(drops)}")
    if not split_rows:
        raise RuntimeError("no tokenized rows")
    if args.output.exists():
        if not args.overwrite:
            raise FileExistsError(f"output exists; pass --overwrite: {args.output}")
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)
    metadata_root = args.output / "metadata"
    metadata_root.mkdir()
    dataset_splits = {}
    for split in ("train", "validation", "protocol_holdout"):
        rows = split_rows[split]
        dataset_splits[split] = Dataset.from_list(
            [{"input_ids": row["input_ids"], "loss_mask": row["loss_mask"]} for row in rows]
        )
        with (metadata_root / f"{split}.jsonl").open("w", encoding="utf-8") as output:
            for row in rows:
                metadata = {key: value for key, value in row.items() if key not in {"input_ids", "loss_mask"}}
                output.write(json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n")
    DatasetDict(dataset_splits).save_to_disk(args.output / "hf_dataset")
    manifest = {
        "schema_version": "studyhub.runtime-sft-tokenized-manifest.v3",
        "status": "TOKENIZED_PENDING_FINAL_AUDIT",
        "model_tokenizer": str(args.model.resolve()),
        "tokenizer_revision": json.loads((args.model / "studyhub_download_manifest.json").read_text())["revision"],
        "max_length": args.max_length,
        "split_counts": {split: len(rows) for split, rows in sorted(split_rows.items())},
        "source_split_counts": {
            source: dict(sorted(counts.items())) for source, counts in sorted(source_counts.items())
        },
        "token_length": {
            "min": min(lengths),
            "p50": percentile(lengths, 0.50),
            "p90": percentile(lengths, 0.90),
            "p95": percentile(lengths, 0.95),
            "p99": percentile(lengths, 0.99),
            "max": max(lengths),
        },
        "all_tokens": all_tokens,
        "loss_tokens": loss_tokens,
        "assistant_token_fraction": round(loss_tokens / all_tokens, 6),
        "source_all_tokens": dict(sorted(source_token_counts.items())),
        "source_loss_tokens": dict(sorted(source_loss_token_counts.items())),
        "input_sha256": sha256(args.input),
        "benchmark_lock": benchmark_lock,
        "selected_manifest": str(selected_manifest_path.resolve()),
        "selected_manifest_sha256": sha256(selected_manifest_path),
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
