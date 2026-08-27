#!/usr/bin/env python3
"""Fail-closed audit for the final Benchmark-v2-disjoint runtime SFT dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from scripts.data.select_runtime_sft_v3 import (
    benchmark_prompt_hashes,
    candidate_prompt_hash,
    sha256,
)
from studyhub_agent.trajectory.runtime_sft import (
    trajectory_fingerprint,
    validate_runtime_trajectory,
)


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _wiki_read_titles(row: dict[str, Any]) -> set[str]:
    titles: set[str] = set()
    for message in row.get("messages", []):
        if message.get("role") != "tool" or message.get("name") != "knowledge_read":
            continue
        try:
            payload = json.loads(str(message.get("content", "")))
        except json.JSONDecodeError:
            continue
        title = " ".join(str(payload.get("title", "")).split()).casefold()
        if title:
            titles.add(title)
    return titles


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=project / "datasets/interim/runtime_sft_v3/candidates.jsonl")
    parser.add_argument("--selected", type=Path, default=project / "datasets/interim/runtime_sft_v3/selected.jsonl")
    parser.add_argument(
        "--tokenized",
        type=Path,
        default=project / "datasets/processed/runtime_sft_v3_qwen35_9b",
    )
    parser.add_argument("--program", type=Path, default=project / "configs/program-v3/training-program-v3.json")
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=project / "benchmarks/studyhub-agent-v2/manifest.json",
    )
    parser.add_argument("--skip-token-row-scan", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project = Path(__file__).resolve().parents[2]
    candidate_manifest_path = args.candidate.with_suffix(".manifest.json")
    selected_manifest_path = args.selected.with_suffix(".manifest.json")
    token_manifest_path = args.tokenized / "manifest.json"
    candidate_manifest = _load(candidate_manifest_path)
    selected_manifest = _load(selected_manifest_path)
    token_manifest = _load(token_manifest_path)
    program = _load(args.program)
    benchmark_manifest = _load(args.benchmark_manifest)
    sft_contract = program["data"]["sft"]
    failures: list[str] = []

    expected_lock = selected_manifest.get("benchmark_lock")
    if not isinstance(expected_lock, dict):
        failures.append("benchmark_lock_missing")
        expected_lock = {}
    for name, manifest in (
        ("candidate", candidate_manifest),
        ("selected", selected_manifest),
        ("tokenized", token_manifest),
    ):
        if manifest.get("benchmark_lock") != expected_lock:
            failures.append(f"{name}_benchmark_lock_mismatch")
    if expected_lock.get("benchmark_manifest_sha256") != sha256(args.benchmark_manifest):
        failures.append("benchmark_manifest_hash_mismatch")
    if expected_lock.get("benchmark_tasks") != sum(benchmark_manifest["counts"].values()):
        failures.append("benchmark_task_count_mismatch")
    if candidate_manifest.get("total") != sft_contract["candidate_trajectories"]:
        failures.append("candidate_count_mismatch")
    if candidate_manifest.get("output_sha256") != sha256(args.candidate):
        failures.append("candidate_file_hash_mismatch")
    if selected_manifest.get("total") != sft_contract["final_trajectories"]:
        failures.append("selected_count_mismatch")
    if selected_manifest.get("output_sha256") != sha256(args.selected):
        failures.append("selected_file_hash_mismatch")
    if selected_manifest.get("input_sha256") != sha256(args.candidate):
        failures.append("selected_candidate_hash_mismatch")
    if token_manifest.get("input_sha256") != sha256(args.selected):
        failures.append("tokenized_selected_hash_mismatch")
    if token_manifest.get("selected_manifest_sha256") != sha256(selected_manifest_path):
        failures.append("tokenized_selected_manifest_hash_mismatch")

    benchmark_hashes, benchmark_task_count = benchmark_prompt_hashes(project, benchmark_manifest)
    selected_ids: set[str] = set()
    content_hashes: set[str] = set()
    split_groups: dict[str, set[str]] = defaultdict(set)
    split_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    source_group_counts: Counter[tuple[str, str]] = Counter()
    runtime_native = 0
    complete = 0
    prompt_overlap = 0
    provenance_failures = 0
    contract_failures = 0
    fingerprint_failures = 0
    forbidden_fields = {
        "expected_calls",
        "gold_query",
        "gold_source_order",
        "gold_trajectory",
        "supporting_facts",
        "oracle_answer",
    }
    forbidden_field_hits = 0
    wiki_title_splits: dict[str, set[str]] = defaultdict(set)
    wiki_rows = 0
    wiki_rows_without_read_titles = 0
    with args.selected.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            record_id = str(row.get("id"))
            if record_id in selected_ids:
                failures.append(f"duplicate_id:{record_id}")
            selected_ids.add(record_id)
            content_hash = str(row.get("content_sha256"))
            if content_hash in content_hashes:
                failures.append(f"duplicate_content:{record_id}")
            content_hashes.add(content_hash)
            if trajectory_fingerprint(row) != content_hash:
                fingerprint_failures += 1
            if validate_runtime_trajectory(row):
                contract_failures += 1
            split = str(row.get("split"))
            source = str(row.get("source_dataset"))
            split_counts[split] += 1
            source_counts[source] += 1
            split_groups[split].add(str(row.get("group_id")))
            source_group_counts[(source, str(row.get("group_id")))] += 1
            runtime_native += int(bool(row.get("runtime_native")))
            complete += int(row.get("trajectory_status") == "complete")
            prompt_overlap += int(candidate_prompt_hash(row) in benchmark_hashes)
            provenance = row.get("provenance", {})
            if not all(provenance.get(key) for key in ("revision", "license", "source_url", "raw_files")):
                provenance_failures += 1
            forbidden_field_hits += len(forbidden_fields & set(row))
            if source == "studyhub_2wiki_replay":
                wiki_rows += 1
                titles = _wiki_read_titles(row)
                if not titles:
                    wiki_rows_without_read_titles += 1
                for title in titles:
                    wiki_title_splits[title].add(split)
    if fingerprint_failures:
        failures.append(f"trajectory_fingerprint_failures:{fingerprint_failures}")
    if contract_failures:
        failures.append(f"runtime_contract_failures:{contract_failures}")
    if provenance_failures:
        failures.append(f"provenance_failures:{provenance_failures}")
    if forbidden_field_hits:
        failures.append(f"forbidden_public_fields:{forbidden_field_hits}")
    if prompt_overlap:
        failures.append(f"benchmark_prompt_overlap:{prompt_overlap}")
    wiki_cross_split_titles = {title: sorted(splits) for title, splits in wiki_title_splits.items() if len(splits) > 1}
    if wiki_rows_without_read_titles:
        failures.append(f"2wiki_rows_without_read_titles:{wiki_rows_without_read_titles}")
    if wiki_cross_split_titles:
        failures.append(f"2wiki_support_title_overlap:{len(wiki_cross_split_titles)}")
    max_2wiki_group_rows = max(
        (count for (source, _group_id), count in source_group_counts.items() if source == "studyhub_2wiki_replay"),
        default=0,
    )
    if max_2wiki_group_rows > 1:
        failures.append(f"2wiki_group_concentration:{max_2wiki_group_rows}")
    if len(selected_ids) != selected_manifest.get("total"):
        failures.append("selected_row_count_mismatch")
    final_trajectories = int(sft_contract["final_trajectories"])
    validation_rows = round(final_trajectories * 0.05)
    protocol_holdout_rows = round(final_trajectories * 0.05)
    expected_splits = {
        "train": final_trajectories - validation_rows - protocol_holdout_rows,
        "validation": validation_rows,
        "protocol_holdout": protocol_holdout_rows,
    }
    if dict(split_counts) != expected_splits:
        failures.append(f"split_count_mismatch:{dict(split_counts)}")
    overlaps = {
        "train_validation": len(split_groups["train"] & split_groups["validation"]),
        "train_protocol_holdout": len(split_groups["train"] & split_groups["protocol_holdout"]),
        "validation_protocol_holdout": len(split_groups["validation"] & split_groups["protocol_holdout"]),
    }
    if any(overlaps.values()):
        failures.append(f"group_overlap:{overlaps}")
    total = len(selected_ids)
    runtime_native_share = runtime_native / max(total, 1)
    if runtime_native_share < sft_contract["runtime_native_multi_turn_min_share"]:
        failures.append("runtime_native_share_below_contract")
    max_source_share = max(source_counts.values(), default=0) / max(total, 1)
    if max_source_share > sft_contract["max_single_source_share"]:
        failures.append("single_source_share_above_contract")
    if selected_manifest.get("largest_semantic_template_cluster_share", 1.0) > 0.02:
        failures.append("semantic_template_cluster_above_two_percent")

    all_tokens = int(token_manifest.get("all_tokens", 0))
    token_min, token_max = sft_contract["allowed_token_range"]
    if not token_min <= all_tokens <= token_max:
        failures.append("token_budget_outside_contract")
    if token_manifest.get("max_length") != 8192:
        failures.append("unexpected_tokenizer_max_length")
    if token_manifest.get("token_length", {}).get("max", 0) > token_manifest.get("max_length", 0):
        failures.append("token_length_overflow")
    if token_manifest.get("split_counts") != expected_splits:
        failures.append("tokenized_split_count_mismatch")

    token_scan = {"status": "SKIPPED", "rows": 0, "all_tokens": 0, "loss_tokens": 0}
    if not args.skip_token_row_scan:
        from datasets import load_from_disk

        dataset = load_from_disk(args.tokenized / "hf_dataset")
        token_scan = {"status": "PASS", "rows": 0, "all_tokens": 0, "loss_tokens": 0}
        for split, expected in expected_splits.items():
            if len(dataset[split]) != expected:
                failures.append(f"hf_split_count_mismatch:{split}")
            for row in dataset[split]:
                input_ids = row["input_ids"]
                loss_mask = row["loss_mask"]
                token_scan["rows"] += 1
                token_scan["all_tokens"] += len(input_ids)
                token_scan["loss_tokens"] += sum(loss_mask)
                if len(input_ids) != len(loss_mask) or not loss_mask or not any(loss_mask):
                    failures.append(f"invalid_loss_mask:{split}:{token_scan['rows']}")
                    break
                if any(value not in {0, 1} for value in loss_mask):
                    failures.append(f"non_binary_loss_mask:{split}:{token_scan['rows']}")
                    break
        if token_scan["all_tokens"] != all_tokens:
            failures.append("hf_all_token_count_mismatch")
        if token_scan["loss_tokens"] != token_manifest.get("loss_tokens"):
            failures.append("hf_loss_token_count_mismatch")

    metadata_hashes = {split: sha256(args.tokenized / "metadata" / f"{split}.jsonl") for split in expected_splits}
    result = {
        "schema_version": "studyhub.runtime-sft-audit.v3",
        "status": "PASS" if not failures else "FAIL",
        "candidate": {
            "rows": candidate_manifest.get("total"),
            "jsonl_sha256": sha256(args.candidate),
            "manifest_sha256": sha256(candidate_manifest_path),
        },
        "selected": {
            "rows": total,
            "jsonl_sha256": sha256(args.selected),
            "manifest_sha256": sha256(selected_manifest_path),
            "split_counts": dict(sorted(split_counts.items())),
            "group_overlap": overlaps,
            "source_counts": dict(sorted(source_counts.items())),
            "runtime_native_count": runtime_native,
            "runtime_native_share": round(runtime_native_share, 6),
            "complete_count": complete,
            "max_source_share": round(max_source_share, 6),
            "semantic_template_clusters": selected_manifest.get("semantic_template_clusters"),
            "largest_semantic_template_cluster_share": selected_manifest.get("largest_semantic_template_cluster_share"),
            "document_isolation": {
                "2wiki_rows": wiki_rows,
                "2wiki_unique_support_titles": len(wiki_title_splits),
                "2wiki_rows_without_read_titles": wiki_rows_without_read_titles,
                "2wiki_max_rows_per_document_component": max_2wiki_group_rows,
                "2wiki_cross_split_support_titles": len(wiki_cross_split_titles),
                "2wiki_cross_split_examples": dict(list(sorted(wiki_cross_split_titles.items()))[:20]),
            },
        },
        "tokenized": {
            "manifest_sha256": sha256(token_manifest_path),
            "hf_dataset_tree_sha256": tree_sha256(args.tokenized / "hf_dataset"),
            "metadata_sha256": metadata_hashes,
            "all_tokens": all_tokens,
            "loss_tokens": token_manifest.get("loss_tokens"),
            "assistant_token_fraction": token_manifest.get("assistant_token_fraction"),
            "token_length": token_manifest.get("token_length"),
            "row_scan": token_scan,
        },
        "benchmark_lock": expected_lock,
        "benchmark_prompt_hashes": benchmark_task_count,
        "benchmark_prompt_overlap": prompt_overlap,
        "failures": failures,
    }
    output = args.output or (args.tokenized / "audit.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
