#!/usr/bin/env python3
"""Build the Spark-teacher plus Open-Agentic retention candidate pool for SFT-2."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for entry in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts.data.audit_spark_hermes_sft2_inputs import (  # noqa: E402
    EligibleTrajectory,
    select_eligible,
    summarize,
)
from scripts.data.select_runtime_sft_v3 import (  # noqa: E402
    candidate_prompt_hash,
    near_signature,
    public_benchmark_prompt_hashes,
    sha256,
)
from scripts.data.tokenize_runtime_sft_v3 import assistant_loss_mask  # noqa: E402
from studyhub_agent.trajectory.runtime_sft import validate_runtime_trajectory  # noqa: E402

STATE_TOOLS = {
    "learning_profile_get",
    "learning_progress_record",
    "material_bookmark_add",
    "study_plan_update",
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _tool_sequence(record: dict[str, Any]) -> list[str]:
    return [
        str(call.get("function", {}).get("name", ""))
        for message in record.get("messages", [])
        if isinstance(message, dict)
        for call in message.get("tool_calls", [])
        if isinstance(call, dict) and call.get("function", {}).get("name")
    ]


def _behavior_tags(record: dict[str, Any]) -> list[str]:
    calls = _tool_sequence(record)
    messages = record.get("messages", [])
    tags: set[str] = set()
    if not calls:
        tags.add("direct_abstention")
    if calls and any(message.get("role") == "tool" for message in messages):
        tags.add("observation_conditioned")
    if sum(message.get("role") == "assistant" for message in messages) > 1:
        tags.add("multi_turn")
    if len(calls) > 1:
        tags.add("multi_tool")
    if record.get("task_family") == "recovery_acl_provider_error":
        tags.add("recovery_negative")
    if set(calls) & STATE_TOOLS:
        tags.add("stateful_function")
    return sorted(tags)


def _abstract_path(record: dict[str, Any]) -> str:
    calls = _tool_sequence(record)
    if not calls:
        return "direct -> final"
    if record.get("task_family") == "recovery_acl_provider_error":
        return "failure -> retry -> final"
    if "knowledge_search" in calls and "knowledge_read" in calls:
        return "search -> read -> final"
    if len(calls) == 1:
        return "single-tool -> final"
    if len(set(calls)) == 1:
        return "single-tool-repeat -> final"
    return "toolA -> toolB -> final"


def _prepare_teacher(row: EligibleTrajectory) -> dict[str, Any]:
    prepared = dict(row.record)
    prepared.update(
        {
            "split": "train",
            "source_family": "spark_teacher",
            "environment_origin": "spark_hermes_actual_observation",
            "behavior_tags": _behavior_tags(prepared),
            "abstract_tool_path": _abstract_path(prepared),
            "tool_path_signature": row.path_signature,
            "policy_quality_tier": "A",
        }
    )
    prepared["tokenization"] = {
        "total_tokens": row.total_tokens,
        "assistant_loss_tokens": row.assistant_tokens,
    }
    return prepared


def build_candidate_pool(
    teacher: list[EligibleTrajectory],
    retention: list[dict[str, Any]],
    *,
    benchmark_prompt_hashes: set[str],
    prohibited_sources: set[str],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    candidates: list[dict[str, Any]] = []
    drops: Counter[str] = Counter()
    ids: set[str] = set()
    contents: set[str] = set()
    near: set[str] = set()
    group_splits: dict[str, str] = {}

    def add(row: dict[str, Any]) -> None:
        failures = validate_runtime_trajectory(row)
        if failures:
            drops["runtime_contract"] += 1
            return
        source = str(row.get("source_dataset", ""))
        if source in prohibited_sources:
            drops["prohibited_source"] += 1
            return
        if row.get("trajectory_status") != "complete":
            drops["not_complete"] += 1
            return
        if candidate_prompt_hash(row) in benchmark_prompt_hashes:
            drops["public_benchmark_prompt_overlap"] += 1
            return
        record_id = str(row["id"])
        content = str(row["content_sha256"])
        signature = near_signature(row)
        split = str(row["split"])
        groups = set(map(str, row.get("source_group_ids", [row["group_id"]])))
        if record_id in ids:
            drops["duplicate_id"] += 1
            return
        if content in contents:
            drops["exact_duplicate"] += 1
            return
        if signature in near:
            drops["deterministic_near_duplicate"] += 1
            return
        if any(group in group_splits and group_splits[group] != split for group in groups):
            drops["group_split_conflict"] += 1
            return
        candidates.append(row)
        ids.add(record_id)
        contents.add(content)
        near.add(signature)
        for group in groups:
            group_splits[group] = split

    for eligible in teacher:
        add(_prepare_teacher(eligible))
    for row in retention:
        add(dict(row))
    return candidates, drops


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--teacher",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/spark_hermes_teacher_v1/accepted.jsonl",
    )
    parser.add_argument(
        "--retention",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/open_agentic_sft_v2/selected.jsonl",
    )
    parser.add_argument(
        "--program",
        type=Path,
        default=PROJECT_ROOT / "configs/program-v4/sft2-spark-retention-v1.json",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(
            "/data/chengjin/studyhub/studyhub-agent/artifacts/areal/model-overlays/"
            "qwen35-4b-base-canonical-tokenizer"
        ),
    )
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/qwen35_4b_sft2_spark_retention_v1/candidates.jsonl",
    )
    parser.add_argument(
        "--teacher-audit-output",
        type=Path,
        default=PROJECT_ROOT / "docs/training/evidence/spark-hermes-sft2-input-audit.json",
    )
    return parser.parse_args()


def main() -> int:
    from transformers import AutoTokenizer

    args = parse_args()
    program = _read_json(args.program)
    benchmark = _read_json(args.benchmark_manifest)
    if program["benchmark_lock"]["manifest_sha256"] != sha256(args.benchmark_manifest):
        raise RuntimeError("Benchmark v2 manifest drift")
    public_hashes, _public_count = public_benchmark_prompt_hashes(PROJECT_ROOT, benchmark)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, trust_remote_code=True)

    def count_tokens(record: dict[str, Any]) -> tuple[int, int]:
        input_ids, loss_mask, _rendered = assistant_loss_mask(tokenizer, record["messages"], record["tools"])
        return len(input_ids), int(sum(loss_mask))

    eligible, teacher_drops, checked = select_eligible(
        _read_jsonl(args.teacher),
        contract=program,
        benchmark_prompt_hashes=public_hashes,
        count_tokens=count_tokens,
    )
    teacher_audit = summarize(eligible, checked=checked, drops=teacher_drops, contract=program)
    teacher_audit["lineage"] = {
        "accepted_sha256": sha256(args.teacher),
        "program_sha256": sha256(args.program),
        "benchmark_manifest_sha256": sha256(args.benchmark_manifest),
    }
    _write_json(args.teacher_audit_output, teacher_audit)
    if teacher_audit["status"] != "PASS":
        print(json.dumps(teacher_audit, ensure_ascii=False, indent=2))
        return 3

    retention = _read_jsonl(args.retention)
    candidates, candidate_drops = build_candidate_pool(
        eligible,
        retention,
        benchmark_prompt_hashes=public_hashes,
        prohibited_sources=set(program["prohibited_sources"]),
    )
    _write_jsonl(args.output, candidates)
    counts = Counter(str(row["source_family"]) for row in candidates)
    manifest = {
        "schema_version": "studyhub.qwen35-4b-sft2-candidate-manifest.v1",
        "status": "CANDIDATE_BUILD_PASS",
        "rows": len(candidates),
        "source_family_rows": dict(sorted(counts.items())),
        "teacher_rows": counts["spark_teacher"],
        "retention_rows": len(candidates) - counts["spark_teacher"],
        "drops": dict(candidate_drops.most_common()),
        "lineage": {
            "output_sha256": sha256(args.output),
            "teacher_sha256": sha256(args.teacher),
            "retention_sha256": sha256(args.retention),
            "program_sha256": sha256(args.program),
            "teacher_audit_sha256": sha256(args.teacher_audit_output),
        },
        "semantic_embedding_audit": "REQUIRED_BEFORE_TOKEN_ALLOCATION",
    }
    _write_json(args.output.with_suffix(".manifest.json"), manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
