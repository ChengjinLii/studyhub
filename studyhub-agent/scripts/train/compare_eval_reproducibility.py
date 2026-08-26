#!/usr/bin/env python3
"""Compare two deterministic Eval32 runs without volatile run identifiers."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROLLOUTS_PER_TASK = 4


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_groups(path: Path) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("split") != "validation":
            raise RuntimeError(f"non-validation row in deterministic eval: {path}")
        groups[str(row["task_id"])].append(row)
    if not groups:
        raise RuntimeError(f"empty deterministic eval: {path}")
    invalid = {
        task_id: len(rows)
        for task_id, rows in sorted(groups.items())
        if len(rows) != ROLLOUTS_PER_TASK
    }
    if invalid:
        raise RuntimeError(f"expected exactly four rollouts per task: {invalid}")
    return dict(groups)


def _signature(row: dict[str, Any]) -> str:
    """Retain policy-visible behavior while dropping time and request identity."""

    trace = row.get("trace", {})
    hermes = trace.get("hermes", {})
    stable = {
        "task_id": row["task_id"],
        "task_family": row["task_family"],
        "source_dataset": row.get("source_dataset"),
        "source_group_id": row.get("source_group_id"),
        "final_answer_sha256": row["final_answer_sha256"],
        "final_answer_length": row["final_answer_length"],
        "final_answer_empty": row["final_answer_empty"],
        "max_steps": row["max_steps"],
        "max_tool_calls": row["max_tool_calls"],
        "reward": row["reward"],
        "trace": {
            "tool_calls": trace.get("tool_calls"),
            "tool_names": trace.get("tool_names"),
            "invalid_tool_calls": trace.get("invalid_tool_calls"),
            "error_codes": trace.get("error_codes"),
            "search_results": trace.get("search_results"),
            "read_sources": trace.get("read_sources"),
            "hermes": {
                "guardrail_halt": hermes.get("guardrail_halt"),
                "api_calls": hermes.get("api_calls"),
                "input_tokens": hermes.get("input_tokens"),
                "output_tokens": hermes.get("output_tokens"),
                "prompt_tokens": hermes.get("prompt_tokens"),
                "completion_tokens": hermes.get("completion_tokens"),
                "total_tokens": hermes.get("total_tokens"),
                "last_prompt_tokens": hermes.get("last_prompt_tokens"),
            },
        },
    }
    return hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def compare(reference: Path, candidate: Path) -> dict[str, Any]:
    reference_groups = _read_groups(reference)
    candidate_groups = _read_groups(candidate)
    if set(reference_groups) != set(candidate_groups):
        missing = sorted(set(reference_groups) - set(candidate_groups))
        extra = sorted(set(candidate_groups) - set(reference_groups))
        raise RuntimeError(
            f"task sets differ; missing={missing[:5]}, extra={extra[:5]}"
        )

    mismatches = []
    matched_rollouts = 0
    for task_id in sorted(reference_groups):
        left = Counter(_signature(row) for row in reference_groups[task_id])
        right = Counter(_signature(row) for row in candidate_groups[task_id])
        matched = sum((left & right).values())
        matched_rollouts += matched
        if left != right:
            mismatches.append(
                {
                    "task_id": task_id,
                    "matched_rollouts": matched,
                    "reference_only": sum((left - right).values()),
                    "candidate_only": sum((right - left).values()),
                }
            )

    tasks = len(reference_groups)
    rollouts = tasks * ROLLOUTS_PER_TASK
    exact = not mismatches
    return {
        "schema_version": "studyhub.eval-reproducibility.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "comparison_contract": {
            "rollouts_per_task": ROLLOUTS_PER_TASK,
            "volatile_fields_ignored": [
                "recorded_at",
                "experiment_name",
                "trial_name",
                "rollout_group_id",
                "rollout_id",
                "run_kind",
            ],
            "stable_fields_include": [
                "final answer SHA/length",
                "reward components and violations",
                "tool trace and read sources",
                "Hermes token and guardrail metadata",
            ],
        },
        "reference": {
            "path": str(reference.resolve()),
            "sha256": _sha256(reference),
        },
        "candidate": {
            "path": str(candidate.resolve()),
            "sha256": _sha256(candidate),
        },
        "tasks": tasks,
        "rollouts": rollouts,
        "exact_task_multisets": tasks - len(mismatches),
        "matched_rollouts": matched_rollouts,
        "matched_rollout_rate": matched_rollouts / rollouts,
        "mismatches": mismatches,
        "status": "EXACT" if exact else "MISMATCH",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = compare(args.reference, args.candidate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "EXACT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
