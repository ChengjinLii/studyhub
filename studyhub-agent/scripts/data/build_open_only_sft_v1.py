#!/usr/bin/env python3
"""Build the token-matched Open-Only 9B SFT control dataset."""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for import_root in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from scripts.data.select_runtime_sft_v3 import (  # noqa: E402
    candidate_prompt_hash,
    near_signature,
    public_benchmark_prompt_hashes,
    semantic_template,
)
from studyhub_agent.trajectory.runtime_sft import stable_hash, validate_runtime_trajectory  # noqa: E402

_CITATION = re.compile(r"\[(?:wiki|paper|studyhub-material|web-material):[^]]+]", re.IGNORECASE)
_CJK = re.compile(r"[\u3400-\u9fff]")


@dataclass(frozen=True)
class InventoryRow:
    record_id: str
    source: str
    split: str
    group_id: str
    position: int
    total_tokens: int
    assistant_tokens: int
    stable_order: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(row for row in root.rglob("*") if row.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]


def final_text(row: dict[str, Any]) -> str:
    return next(
        (
            str(message.get("content", ""))
            for message in reversed(row["messages"])
            if message.get("role") == "assistant" and not message.get("tool_calls")
        ),
        "",
    )


def user_text(row: dict[str, Any]) -> str:
    return next(
        (str(message.get("content", "")) for message in row["messages"] if message.get("role") == "user"),
        "",
    )


def tool_path_signature(row: dict[str, Any]) -> str:
    names = [
        str(call.get("function", {}).get("name", ""))
        for message in row["messages"]
        if message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
    ]
    return " -> ".join(names) if names else "DIRECT"


def language(row: dict[str, Any]) -> str:
    return "zh" if _CJK.search(user_text(row)) else "en"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _best_swap(
    selected: list[InventoryRow],
    available: list[InventoryRow],
    delta: int,
) -> tuple[InventoryRow, InventoryRow] | None:
    if not selected or not available or delta == 0:
        return None
    by_tokens = sorted(available, key=lambda row: (row.assistant_tokens, row.stable_order))
    token_values = [row.assistant_tokens for row in by_tokens]
    best: tuple[int, str, InventoryRow, InventoryRow] | None = None
    for old in selected:
        desired = old.assistant_tokens + delta
        index = bisect.bisect_left(token_values, desired)
        for candidate_index in (index - 1, index):
            if not 0 <= candidate_index < len(by_tokens):
                continue
            new = by_tokens[candidate_index]
            change = new.assistant_tokens - old.assistant_tokens
            if delta > 0 and change <= 0:
                continue
            if delta < 0 and change >= 0:
                continue
            residual = abs(delta - change)
            key = (residual, f"{old.stable_order}:{new.stable_order}", old, new)
            if best is None or key[:2] < best[:2]:
                best = key
    return None if best is None else (best[2], best[3])


def select_fixed_count_for_tokens(
    rows: list[InventoryRow],
    count: int,
    target_tokens: int,
) -> list[InventoryRow]:
    if count > len(rows):
        raise RuntimeError(f"selection asks for {count} rows from a pool of {len(rows)}")
    if count == len(rows):
        return sorted(rows, key=lambda row: row.stable_order)
    ordered_by_length = sorted(rows, key=lambda row: (row.assistant_tokens, row.stable_order))
    minimum = sum(row.assistant_tokens for row in ordered_by_length[:count])
    maximum = sum(row.assistant_tokens for row in ordered_by_length[-count:])
    if not minimum <= target_tokens <= maximum:
        raise RuntimeError(
            f"assistant-token target is infeasible for fixed row count: "
            f"target={target_tokens}, minimum={minimum}, maximum={maximum}"
        )

    target_average = target_tokens / count
    ranked = sorted(
        rows,
        key=lambda row: (abs(row.assistant_tokens - target_average), row.stable_order),
    )
    selected = ranked[:count]
    available = ranked[count:]
    current = sum(row.assistant_tokens for row in selected)
    for _ in range(512):
        delta = target_tokens - current
        if delta == 0:
            break
        swap = _best_swap(selected, available, delta)
        if swap is None:
            break
        old, new = swap
        change = new.assistant_tokens - old.assistant_tokens
        if abs(delta - change) >= abs(delta):
            break
        selected.remove(old)
        available.remove(new)
        selected.append(new)
        available.append(old)
        current += change
    return sorted(selected, key=lambda row: row.stable_order)


def source_audit(rows: list[tuple[dict[str, Any], int, int]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    grouped: dict[str, list[tuple[dict[str, Any], int, int]]] = defaultdict(list)
    for entry in rows:
        grouped[str(entry[0]["source_dataset"])].append(entry)
    for source, entries in sorted(grouped.items()):
        group_counts = Counter(str(row["group_id"]) for row, _total, _loss in entries)
        semantic_counts = Counter(semantic_template(row) for row, _total, _loss in entries)
        path_counts = Counter(tool_path_signature(row) for row, _total, _loss in entries)
        total_tokens = sum(total for _row, total, _loss in entries)
        loss_tokens = sum(loss for _row, _total, loss in entries)
        revisions = sorted({str(row["provenance"].get("revision", "")) for row, _total, _loss in entries})
        licenses = sorted({str(row["provenance"].get("license", "")) for row, _total, _loss in entries})
        transforms = sorted(
            {str(row["provenance"].get("transform_version", "")) for row, _total, _loss in entries}
        )
        result[source] = {
            "rows": len(entries),
            "complete_rows": sum(row.get("trajectory_status") == "complete" for row, _total, _loss in entries),
            "action_only_rows": sum(row.get("trajectory_status") != "complete" for row, _total, _loss in entries),
            "total_tokens": total_tokens,
            "assistant_loss_tokens": loss_tokens,
            "assistant_token_fraction": round(loss_tokens / total_tokens, 6),
            "unique_groups": len(group_counts),
            "rows_per_group": {
                "p50": percentile(list(group_counts.values()), 0.50),
                "p90": percentile(list(group_counts.values()), 0.90),
                "max": max(group_counts.values()),
            },
            "semantic_template_clusters": len(semantic_counts),
            "largest_semantic_template_cluster_share": round(max(semantic_counts.values()) / len(entries), 6),
            "tool_path_signatures": len(path_counts),
            "largest_tool_path_share": round(max(path_counts.values()) / len(entries), 6),
            "language": dict(sorted(Counter(language(row) for row, _total, _loss in entries).items())),
            "citation_rows": sum(bool(_CITATION.search(final_text(row))) for row, _total, _loss in entries),
            "observation_origin": dict(
                sorted(Counter(str(row.get("environment_origin", "")) for row, _total, _loss in entries).items())
            ),
            "quality_tiers": dict(
                sorted(Counter(str(row.get("quality_tier", "")) for row, _total, _loss in entries).items())
            ),
            "revision": revisions,
            "license": licenses,
            "transform_version": transforms,
        }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--program",
        type=Path,
        default=PROJECT_ROOT / "configs/program-v3/open-only-sft-v1.json",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=PROJECT_ROOT / "datasets/processed/runtime_sft_v3_qwen35_9b",
    )
    parser.add_argument(
        "--source-selected",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/runtime_sft_v3/selected.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/open_only_sft_v1",
    )
    parser.add_argument(
        "--processed-output",
        type=Path,
        default=PROJECT_ROOT / "datasets/processed/open_only_sft_v1_qwen35_9b",
    )
    parser.add_argument(
        "--data-card",
        type=Path,
        default=PROJECT_ROOT / "configs/program-v3/open-only-sft-v1-data-card.json",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from datasets import Dataset, DatasetDict, load_from_disk

    program = load_json(args.program)
    if program.get("status") != "AUTHORIZED_PENDING_RUN":
        raise RuntimeError("Open-Only program is not authorized pending run")
    allowed = set(program["allowed_sources"])
    if len(allowed) != 5:
        raise RuntimeError("Open-Only source allowlist drift")
    lineage = program["candidate_lineage"]
    expected_source_hashes = {
        args.source_selected: lineage["selected_jsonl_sha256"],
        args.source_selected.with_suffix(".manifest.json"): lineage["selected_manifest_sha256"],
        args.source_root / "manifest.json": lineage["tokenized_manifest_sha256"],
    }
    for path, expected in expected_source_hashes.items():
        if sha256(path) != expected:
            raise RuntimeError(f"source lineage drift: {path}")

    benchmark_manifest_path = PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json"
    benchmark_manifest = load_json(benchmark_manifest_path)
    benchmark_lock = program["benchmark_lock"]
    if sha256(benchmark_manifest_path) != benchmark_lock["manifest_sha256"]:
        raise RuntimeError("frozen Benchmark v2 manifest drift")
    if benchmark_manifest.get("status") != benchmark_lock["status"]:
        raise RuntimeError("Benchmark v2 is not frozen")
    benchmark_hashes, public_benchmark_rows = public_benchmark_prompt_hashes(PROJECT_ROOT, benchmark_manifest)

    source_dataset = load_from_disk(args.source_root / "hf_dataset")
    source_manifest = load_json(args.source_root / "manifest.json")
    if source_manifest.get("input_sha256") != lineage["selected_jsonl_sha256"]:
        raise RuntimeError("tokenized source is not aligned with the Mixed-v3.0 selected file")

    if args.output.exists() or args.processed_output.exists():
        if not args.overwrite:
            raise FileExistsError("Open-Only output exists; pass --overwrite")
        shutil.rmtree(args.output, ignore_errors=True)
        shutil.rmtree(args.processed_output, ignore_errors=True)
    staging = args.output.with_name(args.output.name + ".partial")
    processed_staging = args.processed_output.with_name(args.processed_output.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(processed_staging, ignore_errors=True)
    staging.mkdir(parents=True)
    processed_staging.mkdir(parents=True)

    inventory: dict[str, list[InventoryRow]] = defaultdict(list)
    candidate_rows_for_audit: list[tuple[dict[str, Any], int, int]] = []
    candidate_file = staging / "candidates.jsonl"
    ids: set[str] = set()
    exact_hashes: set[str] = set()
    near_hashes: set[str] = set()
    groups_by_split: dict[str, set[str]] = defaultdict(set)
    source_complete_counts: Counter[str] = Counter()
    benchmark_overlap: list[str] = []
    with candidate_file.open("w", encoding="utf-8") as candidate_output:
        for split in ("train", "validation", "protocol_holdout"):
            metadata_path = args.source_root / "metadata" / f"{split}.jsonl"
            with metadata_path.open(encoding="utf-8") as metadata_stream:
                for position, (tensor_row, line) in enumerate(
                    zip(source_dataset[split], metadata_stream, strict=True)
                ):
                    row = json.loads(line)
                    source = str(row.get("source_dataset", ""))
                    if source not in allowed or row.get("trajectory_status") != "complete":
                        continue
                    failures = validate_runtime_trajectory(row)
                    if failures:
                        raise RuntimeError(f"runtime contract failure for {row.get('id')}: {failures}")
                    if not isinstance(row.get("provenance"), dict):
                        raise RuntimeError(f"missing provenance: {row.get('id')}")
                    for required in ("revision", "license", "transform_version"):
                        if not row["provenance"].get(required):
                            raise RuntimeError(f"missing provenance {required}: {row.get('id')}")
                    record_id = str(row["id"])
                    if record_id in ids:
                        raise RuntimeError(f"duplicate row id: {record_id}")
                    ids.add(record_id)
                    content_hash = str(row["content_sha256"])
                    if content_hash in exact_hashes:
                        raise RuntimeError(f"exact duplicate in Open-Only candidate: {record_id}")
                    exact_hashes.add(content_hash)
                    near_hash = near_signature(row)
                    if near_hash in near_hashes:
                        raise RuntimeError(f"near duplicate in Open-Only candidate: {record_id}")
                    near_hashes.add(near_hash)
                    if candidate_prompt_hash(row) in benchmark_hashes:
                        benchmark_overlap.append(record_id)
                    input_ids = tensor_row["input_ids"]
                    loss_mask = tensor_row["loss_mask"]
                    if len(input_ids) != len(loss_mask) or not any(loss_mask):
                        raise RuntimeError(f"invalid assistant loss mask: {record_id}")
                    total_tokens = len(input_ids)
                    assistant_tokens = sum(loss_mask)
                    row_split = str(row.get("split", split))
                    if row_split != split:
                        raise RuntimeError(f"metadata split drift for {record_id}: {row_split} != {split}")
                    group_id = str(row["group_id"])
                    groups_by_split[split].add(group_id)
                    source_complete_counts[source] += 1
                    row["tokenization"] = {
                        "total_tokens": total_tokens,
                        "assistant_loss_tokens": assistant_tokens,
                    }
                    candidate_output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    candidate_rows_for_audit.append((row, total_tokens, assistant_tokens))
                    inventory[split].append(
                        InventoryRow(
                            record_id=record_id,
                            source=source,
                            split=split,
                            group_id=group_id,
                            position=position,
                            total_tokens=total_tokens,
                            assistant_tokens=assistant_tokens,
                            stable_order=stable_hash(record_id, salt="open-only-sft-v1-selection-20260827"),
                        )
                    )
    if benchmark_overlap:
        raise RuntimeError(f"Open-Only candidate overlaps public Benchmark prompts: {benchmark_overlap[:5]}")
    overlap = {
        "train_validation": len(groups_by_split["train"] & groups_by_split["validation"]),
        "train_protocol_holdout": len(groups_by_split["train"] & groups_by_split["protocol_holdout"]),
        "validation_protocol_holdout": len(
            groups_by_split["validation"] & groups_by_split["protocol_holdout"]
        ),
    }
    if any(overlap.values()):
        raise RuntimeError(f"source-group split overlap: {overlap}")

    selection = program["selection"]
    source_row_targets = {key: int(value) for key, value in selection["train_source_rows"].items()}
    source_token_targets = {
        key: int(value) for key, value in selection["train_source_assistant_loss_token_targets"].items()
    }
    if sum(source_row_targets.values()) != int(selection["train_rows"]):
        raise RuntimeError("train source row targets do not sum to the controlled sequence budget")
    if set(source_token_targets) != set(source_row_targets):
        raise RuntimeError("source row and assistant-token target keys differ")
    if sum(source_token_targets.values()) != int(selection["target_assistant_loss_tokens"]):
        raise RuntimeError("source assistant-token targets do not sum to the controlled token budget")
    train_by_source: dict[str, list[InventoryRow]] = defaultdict(list)
    for row in inventory["train"]:
        train_by_source[row.source].append(row)
    for source, target in source_row_targets.items():
        if target > len(train_by_source[source]):
            raise RuntimeError(
                f"insufficient complete train rows for {source}: "
                f"{len(train_by_source[source])} < {target}"
            )

    target_loss_tokens = int(selection["target_assistant_loss_tokens"])
    selected_train: list[InventoryRow] = []
    for source, count in source_row_targets.items():
        chosen = select_fixed_count_for_tokens(
            train_by_source[source],
            count,
            source_token_targets[source],
        )
        selected_train.extend(chosen)
    selected_train = sorted(selected_train, key=lambda row: row.stable_order)
    actual_train_tokens = sum(row.assistant_tokens for row in selected_train)
    tolerance = round(target_loss_tokens * float(selection["assistant_loss_token_tolerance_fraction"]))
    if abs(actual_train_tokens - target_loss_tokens) > tolerance:
        raise RuntimeError(
            f"assistant-loss token budget mismatch: target={target_loss_tokens}, "
            f"actual={actual_train_tokens}, tolerance={tolerance}"
        )

    selected_ids_by_split = {
        "train": {row.record_id for row in selected_train},
        "validation": {row.record_id for row in inventory["validation"]},
        "protocol_holdout": {row.record_id for row in inventory["protocol_holdout"]},
    }
    selected_rows_for_audit: list[tuple[dict[str, Any], int, int]] = []
    selected_jsonl = staging / "selected.jsonl"
    selected_metadata_root = processed_staging / "metadata"
    selected_metadata_root.mkdir()
    dataset_splits: dict[str, Dataset] = {}
    selected_split_counts: Counter[str] = Counter()
    selected_source_split_counts: dict[str, Counter[str]] = defaultdict(Counter)
    selected_total_tokens = 0
    selected_loss_tokens = 0
    selected_lengths: list[int] = []
    with selected_jsonl.open("w", encoding="utf-8") as selected_output:
        for split in ("train", "validation", "protocol_holdout"):
            tensors = {"input_ids": [], "loss_mask": []}
            metadata_output_path = selected_metadata_root / f"{split}.jsonl"
            with (
                (args.source_root / "metadata" / f"{split}.jsonl").open(encoding="utf-8") as metadata_stream,
                metadata_output_path.open("w", encoding="utf-8") as metadata_output,
            ):
                for tensor_row, line in zip(source_dataset[split], metadata_stream, strict=True):
                    row = json.loads(line)
                    record_id = str(row.get("id", ""))
                    if record_id not in selected_ids_by_split[split]:
                        continue
                    total_tokens = len(tensor_row["input_ids"])
                    assistant_tokens = sum(tensor_row["loss_mask"])
                    row["tokenization"] = {
                        "total_tokens": total_tokens,
                        "assistant_loss_tokens": assistant_tokens,
                    }
                    selected_output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    metadata_output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    tensors["input_ids"].append(tensor_row["input_ids"])
                    tensors["loss_mask"].append(tensor_row["loss_mask"])
                    selected_rows_for_audit.append((row, total_tokens, assistant_tokens))
                    selected_split_counts[split] += 1
                    selected_source_split_counts[str(row["source_dataset"])][split] += 1
                    selected_total_tokens += total_tokens
                    selected_loss_tokens += assistant_tokens
                    selected_lengths.append(total_tokens)
            dataset_splits[split] = Dataset.from_dict(tensors)
    DatasetDict(dataset_splits).save_to_disk(processed_staging / "hf_dataset")

    train_source_loss = Counter()
    train_source_total = Counter()
    for row, total, loss in selected_rows_for_audit:
        if row["split"] == "train":
            train_source_loss[str(row["source_dataset"])] += loss
            train_source_total[str(row["source_dataset"])] += total
    train_actual = sum(train_source_loss.values())
    source_loss_shares = {
        source: round(tokens / train_actual, 6) for source, tokens in sorted(train_source_loss.items())
    }
    candidate_manifest = {
        "schema_version": "studyhub.open-only-sft-candidate-manifest.v1",
        "status": "FILTERED_COMPLETE_OPEN_ONLY",
        "source_selected_sha256": sha256(args.source_selected),
        "rows": len(candidate_rows_for_audit),
        "source_complete_counts": dict(sorted(source_complete_counts.items())),
        "allowed_sources": sorted(allowed),
        "action_only_rows": 0,
        "runtime_contract_failures": 0,
        "exact_duplicates": 0,
        "near_duplicates": 0,
        "public_benchmark_rows_hashed": public_benchmark_rows,
        "benchmark_prompt_overlap": 0,
        "sealed_content_read": False,
        "benchmark_lock": benchmark_lock,
        "output_sha256": sha256(candidate_file),
    }
    write_json(staging / "candidates.manifest.json", candidate_manifest)

    selected_manifest = {
        "schema_version": "studyhub.open-only-sft-selected-manifest.v1",
        "status": "ACCEPTED_FOR_CONTROLLED_SFT",
        "seed": int(program["seed"]),
        "split_counts": dict(selected_split_counts),
        "source_split_counts": {
            source: dict(sorted(counts.items())) for source, counts in sorted(selected_source_split_counts.items())
        },
        "train_rows": len(selected_train),
        "target_assistant_loss_tokens": target_loss_tokens,
        "actual_assistant_loss_tokens": actual_train_tokens,
        "assistant_loss_token_delta": actual_train_tokens - target_loss_tokens,
        "assistant_loss_token_delta_fraction": round(
            (actual_train_tokens - target_loss_tokens) / target_loss_tokens, 8
        ),
        "train_source_assistant_loss_tokens": dict(sorted(train_source_loss.items())),
        "train_source_total_tokens": dict(sorted(train_source_total.items())),
        "train_source_assistant_loss_shares": source_loss_shares,
        "group_overlap": overlap,
        "action_only_rows": 0,
        "runtime_contract_failures": 0,
        "exact_duplicates": 0,
        "near_duplicates": 0,
        "benchmark_prompt_overlap": 0,
        "sealed_content_read": False,
        "candidate_sha256": sha256(candidate_file),
        "candidate_manifest_sha256": sha256(staging / "candidates.manifest.json"),
        "output_sha256": sha256(selected_jsonl),
        "benchmark_lock": benchmark_lock,
    }
    write_json(staging / "selected.manifest.json", selected_manifest)

    candidate_audit = source_audit(candidate_rows_for_audit)
    selected_audit = source_audit(selected_rows_for_audit)
    source_audit_payload = {
        "schema_version": "studyhub.open-only-sft-source-audit.v1",
        "status": "PASS",
        "candidate": candidate_audit,
        "selected": selected_audit,
        "selection_shortfalls": {
            "coig_exam": (
                "Complete-row capacity limits the train assistant-token share below the requested 15-20% range."
            ),
            "studyhub_qasper_replay": (
                "Complete-row capacity limits the train assistant-token share below the requested 15-20% range."
            ),
            "studyhub_2wiki_replay": (
                "Receives the unavoidable residual token budget after complete-row capacity limits in COIG and QASPER."
            ),
        },
    }
    write_json(staging / "source-audit.json", source_audit_payload)

    token_manifest = {
        "schema_version": "studyhub.open-only-sft-tokenized-manifest.v1",
        "status": "TOKENIZED_AND_AUDITED",
        "model_tokenizer": source_manifest["model_tokenizer"],
        "tokenizer_revision": source_manifest["tokenizer_revision"],
        "max_length": source_manifest["max_length"],
        "split_counts": dict(selected_split_counts),
        "source_split_counts": selected_manifest["source_split_counts"],
        "token_length": {
            "min": min(selected_lengths),
            "p50": percentile(selected_lengths, 0.50),
            "p90": percentile(selected_lengths, 0.90),
            "p95": percentile(selected_lengths, 0.95),
            "p99": percentile(selected_lengths, 0.99),
            "max": max(selected_lengths),
        },
        "all_tokens": selected_total_tokens,
        "assistant_loss_tokens": selected_loss_tokens,
        "train_assistant_loss_tokens": train_actual,
        "assistant_token_fraction": round(selected_loss_tokens / selected_total_tokens, 6),
        "selected_sha256": sha256(selected_jsonl),
        "selected_manifest_sha256": sha256(staging / "selected.manifest.json"),
        "benchmark_lock": benchmark_lock,
    }
    write_json(processed_staging / "manifest.json", token_manifest)
    token_manifest["hf_dataset_tree_sha256"] = tree_sha256(processed_staging / "hf_dataset")
    write_json(processed_staging / "manifest.json", token_manifest)

    data_card = {
        "schema_version": "studyhub.open-only-sft-data-card.v1",
        "dataset_id": "open-only-sft-v1-qwen35-9b",
        "status": "ACCEPTED_FOR_CONTROLLED_SFT",
        "rows": {
            "candidate": len(candidate_rows_for_audit),
            "selected": sum(selected_split_counts.values()),
            **dict(selected_split_counts),
        },
        "selection": {
            "target_train_assistant_loss_tokens": target_loss_tokens,
            "actual_train_assistant_loss_tokens": train_actual,
            "delta_fraction": selected_manifest["assistant_loss_token_delta_fraction"],
            "planned_optimizer_updates": int(program["recipe"]["planned_optimizer_updates"]),
            "train_source_assistant_loss_shares": source_loss_shares,
        },
        "tokenization": token_manifest,
        "isolation": {
            "studyhub_custom_rows": 0,
            "action_only_rows": 0,
            "benchmark_prompt_overlap": 0,
            "sealed_exposure": False,
            "exact_duplicates": 0,
            "near_duplicates": 0,
            "group_overlap": overlap,
            "benchmark_manifest_sha256": benchmark_lock["manifest_sha256"],
        },
        "lineage": {
            "program_sha256": sha256(args.program),
            "candidate_sha256": sha256(candidate_file),
            "candidate_manifest_sha256": sha256(staging / "candidates.manifest.json"),
            "selected_sha256": sha256(selected_jsonl),
            "selected_manifest_sha256": sha256(staging / "selected.manifest.json"),
            "token_manifest_sha256": sha256(processed_staging / "manifest.json"),
            "hf_dataset_tree_sha256": token_manifest["hf_dataset_tree_sha256"],
        },
        "audit": {"status": "PASS", "failures": 0},
        "limitations": [
            (
                "2Wiki and QASPER rows are open-source-derived oracle/replay trajectories, "
                "not autonomous teacher policies."
            ),
            (
                "COIG and QASPER complete-row capacity is insufficient for their requested assistant-token "
                "share ranges; the residual is assigned to 2Wiki."
            ),
            (
                "This dataset is designed for a controlled directional comparison, "
                "not a claim of general agent improvement."
            ),
        ],
    }

    os.replace(staging, args.output)
    os.replace(processed_staging, args.processed_output)
    write_json(args.data_card, data_card)
    print(json.dumps(data_card, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
