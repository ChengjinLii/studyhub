#!/usr/bin/env python3
"""Fail-closed audit for Spark-Hermes trajectories entering 4B SFT-2."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for entry in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts.data.select_runtime_sft_v3 import (  # noqa: E402
    candidate_prompt_hash,
    public_benchmark_prompt_hashes,
    sha256,
)
from scripts.data.tokenize_runtime_sft_v3 import assistant_loss_mask  # noqa: E402
from studyhub_agent.trajectory.runtime_sft import (  # noqa: E402
    stable_hash,
    trajectory_fingerprint,
    validate_runtime_trajectory,
)

TokenCounter = Callable[[dict[str, Any]], tuple[int, int]]


@dataclass(frozen=True, slots=True)
class EligibleTrajectory:
    record: dict[str, Any]
    total_tokens: int
    assistant_tokens: int
    group_id: str
    path_signature: str
    stable_order: str


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
    temporary.replace(path)


def _tool_names(record: dict[str, Any]) -> set[str]:
    schemas = {
        str(tool.get("function", {}).get("name", ""))
        for tool in record.get("tools", [])
        if isinstance(tool, dict)
    }
    calls = {
        str(call.get("function", {}).get("name", ""))
        for message in record.get("messages", [])
        if isinstance(message, dict)
        for call in message.get("tool_calls", [])
        if isinstance(call, dict)
    }
    return (schemas | calls) - {""}


def _verification_failures(record: dict[str, Any]) -> list[str]:
    verification = record.get("verification")
    if not isinstance(verification, dict):
        return ["verification_missing"]
    failures = []
    list_fields = (
        "invalid_citations",
        "disallowed_citations",
        "missing_answer_concept_groups",
        "missing_tool_groups",
        "provider_errors",
        "present_forbidden_terms",
    )
    for field in list_fields:
        if verification.get(field):
            failures.append(f"verification:{field}")
    if verification.get("verifier_mode") != "path_agnostic_v2":
        failures.append("verification:verifier_mode")
    return failures


def _row_failures(
    record: dict[str, Any],
    *,
    contract: dict[str, Any],
    benchmark_prompt_hashes: set[str],
) -> list[str]:
    failures = list(validate_runtime_trajectory(record))
    gate = contract["teacher_gate"]
    if record.get("source_dataset") != gate["source_dataset"]:
        failures.append("source_dataset")
    if record.get("quality_tier") not in set(gate["allowed_quality_tiers"]):
        failures.append("quality_tier_not_teacher_verified")
    if record.get("trajectory_status") != "complete":
        failures.append("trajectory_not_complete")
    direct = record.get("task_family") == "direct_abstention"
    if not record.get("runtime_native") and not direct:
        failures.append("not_runtime_native")
    teacher = record.get("teacher", {})
    if teacher.get("controller") != gate["required_teacher_controller"]:
        failures.append("teacher_controller")
    if teacher.get("interface") != gate["required_teacher_interface"]:
        failures.append("teacher_interface")
    if teacher.get("model") != gate["required_teacher_model"]:
        failures.append("teacher_model")
    if teacher.get("hermes_commit") != gate["required_hermes_commit"]:
        failures.append("hermes_commit")
    replay_tools = _tool_names(record) & set(gate["replay_only_tools"])
    if replay_tools:
        failures.append("replay_only_tool:" + ",".join(sorted(replay_tools)))
    if candidate_prompt_hash(record) in benchmark_prompt_hashes:
        failures.append("public_benchmark_prompt_overlap")
    if record.get("content_sha256") != trajectory_fingerprint(record):
        failures.append("content_sha256")
    failures.extend(_verification_failures(record))
    return sorted(set(failures))


def select_eligible(
    records: Iterable[dict[str, Any]],
    *,
    contract: dict[str, Any],
    benchmark_prompt_hashes: set[str],
    count_tokens: TokenCounter,
) -> tuple[list[EligibleTrajectory], Counter[str], int]:
    gate = contract["teacher_gate"]
    prepared: list[EligibleTrajectory] = []
    drops: Counter[str] = Counter()
    checked = 0
    for record in records:
        checked += 1
        failures = _row_failures(
            record,
            contract=contract,
            benchmark_prompt_hashes=benchmark_prompt_hashes,
        )
        if failures:
            drops.update(failures)
            continue
        total_tokens, assistant_tokens = count_tokens(record)
        if assistant_tokens <= 0:
            drops["assistant_loss_tokens_zero"] += 1
            continue
        group_id = str(record["group_id"])
        path = str(record.get("teacher", {}).get("path_signature", "DIRECT"))
        prepared.append(
            EligibleTrajectory(
                record=record,
                total_tokens=total_tokens,
                assistant_tokens=assistant_tokens,
                group_id=group_id,
                path_signature=path,
                stable_order=stable_hash(str(record["id"]), salt="spark-hermes-sft2-gate-v1"),
            )
        )

    selected: list[EligibleTrajectory] = []
    contents: set[str] = set()
    group_counts: Counter[str] = Counter()
    group_paths: Counter[tuple[str, str]] = Counter()
    max_group = int(gate["maximum_rows_per_source_group"])
    max_group_path = int(gate["maximum_rows_per_source_group_and_path"])
    for row in sorted(prepared, key=lambda item: item.stable_order):
        content = str(row.record["content_sha256"])
        group_path = (row.group_id, row.path_signature)
        if content in contents:
            drops["exact_duplicate"] += 1
            continue
        if group_counts[row.group_id] >= max_group:
            drops["source_group_cap"] += 1
            continue
        if group_paths[group_path] >= max_group_path:
            drops["source_group_path_cap"] += 1
            continue
        selected.append(row)
        contents.add(content)
        group_counts[row.group_id] += 1
        group_paths[group_path] += 1
    return selected, drops, checked


def summarize(
    selected: list[EligibleTrajectory],
    *,
    checked: int,
    drops: Counter[str],
    contract: dict[str, Any],
) -> dict[str, Any]:
    gate = contract["teacher_gate"]
    assistant_tokens = sum(row.assistant_tokens for row in selected)
    total_tokens = sum(row.total_tokens for row in selected)
    path_counts = Counter(row.path_signature for row in selected)
    family_counts = Counter(str(row.record.get("task_family", "unknown")) for row in selected)
    tool_counts: Counter[str] = Counter()
    for row in selected:
        tool_counts.update(_tool_names(row.record))
    failures = []
    if len(selected) < int(gate["minimum_selected_rows"]):
        failures.append("minimum_selected_rows")
    if assistant_tokens < int(gate["minimum_assistant_loss_tokens"]):
        failures.append("minimum_assistant_loss_tokens")
    return {
        "schema_version": "studyhub.spark-hermes-sft2-input-audit.v1",
        "status": "PASS" if not failures else "BLOCKED_INSUFFICIENT_VERIFIED_TEACHER_DATA",
        "checked_rows": checked,
        "selected_rows": len(selected),
        "dropped_rows": checked - len(selected),
        "assistant_loss_tokens": assistant_tokens,
        "total_tokens": total_tokens,
        "assistant_fraction": round(assistant_tokens / max(total_tokens, 1), 8),
        "unique_source_groups": len({row.group_id for row in selected}),
        "unique_path_signatures": len(path_counts),
        "largest_path_share": round(max(path_counts.values(), default=0) / max(len(selected), 1), 8),
        "family_counts": dict(sorted(family_counts.items())),
        "tool_counts": dict(sorted(tool_counts.items())),
        "drop_reasons": dict(drops.most_common()),
        "gate_failures": failures,
        "selected_ids_sha256": hashlib.sha256(
            "\n".join(sorted(str(row.record["id"]) for row in selected)).encode()
        ).hexdigest(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--accepted",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/codex_hermes_teacher_v1/accepted.jsonl",
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
        default=PROJECT_ROOT / "docs/training/evidence/spark-hermes-sft2-input-audit.json",
    )
    return parser.parse_args()


def main() -> int:
    from transformers import AutoTokenizer

    args = parse_args()
    contract = _read_json(args.program)
    benchmark_manifest = _read_json(args.benchmark_manifest)
    benchmark_hashes, _public_tasks = public_benchmark_prompt_hashes(PROJECT_ROOT, benchmark_manifest)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, trust_remote_code=True)

    def count_tokens(record: dict[str, Any]) -> tuple[int, int]:
        input_ids, loss_mask, _rendered = assistant_loss_mask(tokenizer, record["messages"], record["tools"])
        return len(input_ids), int(sum(loss_mask))

    selected, drops, checked = select_eligible(
        _read_jsonl(args.accepted),
        contract=contract,
        benchmark_prompt_hashes=benchmark_hashes,
        count_tokens=count_tokens,
    )
    report = summarize(selected, checked=checked, drops=drops, contract=contract)
    report["lineage"] = {
        "accepted_sha256": sha256(args.accepted),
        "program_sha256": sha256(args.program),
        "benchmark_manifest_sha256": sha256(args.benchmark_manifest),
        "tokenizer_path": str(args.model.resolve()),
    }
    _write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
