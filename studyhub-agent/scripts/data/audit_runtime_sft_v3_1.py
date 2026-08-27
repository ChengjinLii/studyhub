#!/usr/bin/env python3
"""Audit runtime-SFT-v3.1 teacher candidate without opening sealed benchmark files."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for entry in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts.data.audit_runtime_sft_v3_by_source import final_answer, language, observation_origin, tool_signature
from scripts.data.build_runtime_sft_v3_1 import CUSTOM_SOURCES
from scripts.data.select_runtime_sft_v3 import (
    candidate_prompt_hash,
    public_benchmark_prompt_hashes,
    semantic_template,
    sha256,
)
from studyhub_agent.trajectory.runtime_sft import validate_runtime_trajectory


def _percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_audit(selected: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    benchmark_path = PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    public_hashes, public_tasks = public_benchmark_prompt_hashes(PROJECT_ROOT, benchmark)
    authorization = json.loads(
        (PROJECT_ROOT / "configs/program-v3/overnight-sft-baseline-authorization.json").read_text(encoding="utf-8")
    )
    expected_base = authorization["lineage"]["selected_jsonl_sha256"]
    source: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "rows": 0,
            "split": Counter(),
            "quality": Counter(),
            "status": Counter(),
            "groups": Counter(),
            "clusters": Counter(),
            "paths": Counter(),
            "answers": Counter(),
            "language": Counter(),
            "observation_origin": Counter(),
            "runtime_native": 0,
        }
    )
    failures: list[str] = []
    split_groups: dict[str, set[str]] = defaultdict(set)
    ids: set[str] = set()
    contents: set[str] = set()
    prompt_overlap = 0
    total = 0
    action_only = 0
    runtime_failures = 0
    with selected.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            total += 1
            row_failures = validate_runtime_trajectory(row)
            runtime_failures += int(bool(row_failures))
            row_id = str(row["id"])
            content = str(row["content_sha256"])
            if row_id in ids:
                failures.append(f"duplicate_id:{row_id}")
            if content in contents:
                failures.append(f"duplicate_content:{row_id}")
            ids.add(row_id)
            contents.add(content)
            prompt_overlap += int(candidate_prompt_hash(row) in public_hashes)
            split = str(row["split"])
            split_groups[split].add(str(row["group_id"]))
            action_only += int(row.get("trajectory_status") == "action_only")
            name = str(row["source_dataset"])
            item = source[name]
            item["rows"] += 1
            item["split"][split] += 1
            item["quality"][str(row.get("quality_tier"))] += 1
            item["status"][str(row.get("trajectory_status"))] += 1
            item["groups"][str(row["group_id"])] += 1
            item["clusters"][semantic_template(row)] += 1
            item["paths"][tool_signature(row)] += 1
            answer = final_answer(row)
            item["answers"][hashlib.sha256(answer.casefold().strip().encode()).hexdigest()[:20]] += 1
            item["language"][language(row)] += 1
            item["observation_origin"][observation_origin(row)] += 1
            item["runtime_native"] += int(bool(row.get("runtime_native")))
    overlap = {
        "train_validation": len(split_groups["train"] & split_groups["validation"]),
        "train_protocol_holdout": len(split_groups["train"] & split_groups["protocol_holdout"]),
        "validation_protocol_holdout": len(split_groups["validation"] & split_groups["protocol_holdout"]),
    }
    sources: dict[str, Any] = {}
    for name, item in sorted(source.items()):
        rows = int(item["rows"])
        groups = list(item["groups"].values())
        clusters = list(item["clusters"].values())
        paths = list(item["paths"].values())
        answers = list(item["answers"].values())
        sources[name] = {
            "rows": rows,
            "share": round(rows / max(total, 1), 6),
            "split": dict(sorted(item["split"].items())),
            "quality_tiers": dict(sorted(item["quality"].items())),
            "trajectory_status": dict(sorted(item["status"].items())),
            "runtime_native_share": round(item["runtime_native"] / max(rows, 1), 6),
            "unique_groups": len(groups),
            "rows_per_group": {
                "p50": _percentile(groups, 0.50),
                "p90": _percentile(groups, 0.90),
                "max": max(groups, default=0),
            },
            "semantic_template_clusters": len(clusters),
            "largest_semantic_template_share": round(max(clusters, default=0) / max(rows, 1), 6),
            "tool_sequence_signatures": len(paths),
            "largest_tool_sequence_share": round(max(paths, default=0) / max(rows, 1), 6),
            "final_answer_signatures": len(answers),
            "largest_final_answer_share": round(max(answers, default=0) / max(rows, 1), 6),
            "language": dict(sorted(item["language"].items())),
            "observation_origin": dict(sorted(item["observation_origin"].items())),
        }
    constraints = {
        "candidate_hash_matches_manifest": sha256(selected) == manifest.get("candidate_sha256"),
        "base_hash_is_frozen_v3": manifest.get("base_sha256") == expected_base,
        "rows_45k_to_50k": 45_000 <= total <= 50_000,
        "action_only_at_most_5_percent": action_only / max(total, 1) <= 0.05,
        "single_source_at_most_25_percent": max((row["share"] for row in sources.values()), default=0) <= 0.25,
        "custom_source_at_most_15_percent": all(
            row["share"] <= 0.15 for name, row in sources.items() if name in CUSTOM_SOURCES
        ),
        "group_split_overlap_zero": not any(overlap.values()),
        "public_benchmark_prompt_overlap_zero": prompt_overlap == 0,
        "runtime_contract_valid": runtime_failures == 0,
        "sealed_task_files_read_false": manifest.get("sealed_task_files_read") is False,
    }
    if not all(constraints.values()):
        failures.extend(key for key, passed in constraints.items() if not passed)
    teacher_rows = sources.get("studyhub_teacher_v1", {}).get("rows", 0)
    enough_teacher = teacher_rows >= 500
    if failures:
        status = "FAIL"
    elif enough_teacher:
        status = "PASS"
    else:
        status = "PASS_CANDIDATE_ONLY_INSUFFICIENT_TEACHER"
    return {
        "schema_version": "studyhub.runtime-sft-v3.1-candidate-audit.v1",
        "status": status,
        "formal_release": False,
        "candidate_manifest_status": manifest.get("status"),
        "candidate_sha256": sha256(selected),
        "candidate_manifest_sha256": sha256(manifest_path),
        "base_sha256": manifest.get("base_sha256"),
        "rows": total,
        "action_only_rows": action_only,
        "action_only_share": round(action_only / max(total, 1), 6),
        "teacher_rows": teacher_rows,
        "teacher_minimum_useful_target_met": enough_teacher,
        "split_group_overlap": overlap,
        "public_benchmark_tasks_checked": public_tasks,
        "public_benchmark_prompt_overlap": prompt_overlap,
        "sealed_task_files_read": False,
        "sealed_overlap_recheck": "INHERITED_FROM_FROZEN_V3_SOURCE_LOCK_NOT_RECOMPUTED",
        "tokenization_status": "NOT_RUN_CANDIDATE_ONLY",
        "constraints": constraints,
        "sources": sources,
        "failures": failures,
    }


def render_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Runtime-SFT-v3.1 Teacher Candidate Audit",
        "",
        f"Status: `{audit['status']}`",
        f"Candidate SHA-256: `{audit['candidate_sha256']}`",
        f"Teacher rows: `{audit['teacher_rows']}`",
        f"Sealed task files read: `{str(audit['sealed_task_files_read']).lower()}`",
        "",
        "This is a candidate derived from immutable runtime-SFT-v3.0. It is not a formal release "
        "and is not used by the overnight v3.0 baseline.",
        "",
        "## Constraints",
        "",
        "| Check | Result |",
        "| --- | --- |",
    ]
    for key, passed in audit["constraints"].items():
        lines.append(f"| {key} | {'PASS' if passed else 'FAIL'} |")
    lines.extend(
        [
            "",
            "## Source Distribution",
            "",
            "| Source | Rows | Share | Complete | Action-only | Runtime-native | Groups | "
            "Group p90/max | Paths | Largest path |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, row in audit["sources"].items():
        status = row["trajectory_status"]
        lines.append(
            f"| {name} | {row['rows']:,} | {row['share']:.2%} | {status.get('complete', 0):,} | "
            f"{status.get('action_only', 0):,} | {row['runtime_native_share']:.2%} | {row['unique_groups']:,} | "
            f"{row['rows_per_group']['p90']}/{row['rows_per_group']['max']} | "
            f"{row['tool_sequence_signatures']:,} | {row['largest_tool_sequence_share']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Teacher rows replace weak action-only rows first. Remaining action-only excess is replaced "
            "with complete, benchmark-disjoint rows from the existing audited candidate pool. The candidate "
            "keeps group-disjoint train/validation/holdout splits and does not open Sealed-A/B. Token "
            "statistics remain unavailable until a candidate reaches the 500 accepted-teacher threshold "
            "and is separately tokenized.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--selected",
        type=Path,
        default=PROJECT_ROOT / "datasets/interim/runtime_sft_v3_1/selected.jsonl",
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=PROJECT_ROOT / "docs/training/evidence/runtime-sft-v3.1-candidate-audit.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=PROJECT_ROOT / "docs/training/RUNTIME_SFT_V3_1_CANDIDATE_AUDIT.md",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = args.manifest or args.selected.with_suffix(".manifest.json")
    audit = build_audit(args.selected, manifest)
    _write_json(args.json_output, audit)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(audit), encoding="utf-8")
    print(json.dumps({"status": audit["status"], "json": str(args.json_output)}, ensure_ascii=False))
    return 0 if audit["status"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
