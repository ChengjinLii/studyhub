#!/usr/bin/env python3
# ruff: noqa: E501 - generated Markdown lines remain readable in source
"""Quantify Benchmark v1 replication and semantic-shape limitations without editing v1."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v1.schema import load_jsonl
from studyhub_agent.benchmark_v2.schema import artifact_timestamp

_ID = re.compile(r"(?:sh:)?[a-f0-9-]{8,}|\b\d+\b", re.I)
_DATE = re.compile(r"\b(?:19|20)\d{2}(?:[-/.年]\d{1,2})?(?:[-/.月]\d{1,2})?日?\b")
_SPACE = re.compile(r"\s+")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values: list[int], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lo, hi = math.floor(index), math.ceil(index)
    if lo == hi:
        return float(ordered[lo])
    return ordered[lo] * (hi - index) + ordered[hi] * (index - lo)


def normalize_request(task: dict[str, Any]) -> str:
    text = str(task["user_request"]).casefold()
    metadata = dict(task.get("metadata", {}))
    replacements = [
        str(metadata.get("source_group_id", "")),
        str(task.get("task_id", "")),
    ]
    for value in replacements:
        if value:
            text = text.replace(value.casefold(), " <ENTITY> ")
    text = _DATE.sub(" <DATE> ", text)
    text = _ID.sub(" <ID> ", text)
    text = re.sub(r"[\"“”'‘’][^\"“”'‘’]{2,80}[\"“”'‘’]", " <QUOTED_ENTITY> ", text)
    text = re.sub(r"\b(?:minutes?|marks?|score|material|资料|分钟|分数|日期|地点)\s*[:：]?\s*<ID>", " <SLOT> ", text)
    return _SPACE.sub(" ", text).strip()


def semantic_shape(task: dict[str, Any], grader: dict[str, Any], environment: dict[str, Any]) -> str:
    process = grader.get("process", {})
    shape = {
        "capability": task["capability_id"],
        "request": normalize_request(task),
        "objective_mode": grader.get("objective", {}).get("mode"),
        "tools": sorted(task.get("available_tools", [])),
        "required_families": process.get("required_tool_families", []),
        "failure_shape": [
            [row.get("tool"), row.get("occurrence"), row.get("error_code")]
            for row in environment.get("failure_schedule", [])
        ],
        "fixture_counts": {
            key: len(environment.get(key, []))
            for key in ("inline_documents", "web_pages", "personal_memories", "collective_memories")
        },
    }
    return hashlib.sha256(json.dumps(shape, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def summarize_counts(values: Counter[str]) -> dict[str, Any]:
    counts = list(values.values())
    return {
        "unique": len(values),
        "mean": round(statistics.fmean(counts), 4) if counts else 0.0,
        "p50": percentile(counts, 0.50),
        "p90": percentile(counts, 0.90),
        "max": max(counts, default=0),
        "largest_share": round(max(counts, default=0) / sum(counts), 6) if counts else 0.0,
    }


def audit(args: argparse.Namespace) -> dict[str, Any]:
    public_root = args.public_root.resolve()
    hidden_root = args.hidden_root.resolve()
    splits = {
        "regression": load_jsonl(public_root / "regression/tasks.jsonl"),
        "development": load_jsonl(public_root / "development/tasks.jsonl"),
        "sealed": load_jsonl(hidden_root / "tasks/sealed.jsonl"),
    }
    environments = {
        split: {str(row["task_id"]): row for row in load_jsonl(hidden_root / f"environments/{split}.jsonl")}
        for split in splits
    }
    graders = {
        split: {str(row["task_id"]): row for row in load_jsonl(hidden_root / f"graders/{split}.jsonl")}
        for split in splits
    }
    corpora = {path.stem: load_jsonl(path) for path in sorted((hidden_root / "corpora").glob("*.jsonl"))}
    split_reports: dict[str, Any] = {}
    for split, tasks in splits.items():
        normalized = Counter(normalize_request(task) for task in tasks)
        semantic = Counter(
            semantic_shape(task, graders[split][str(task["task_id"])], environments[split][str(task["task_id"])])
            for task in tasks
        )
        source_groups = Counter(str(task.get("metadata", {}).get("source_group_id", "MISSING")) for task in tasks)
        environment_shapes = Counter(
            json.dumps(
                {
                    "tools": row.get("available_tools", []),
                    "inline": len(row.get("inline_documents", [])),
                    "web": len(row.get("web_pages", [])),
                    "personal": len(row.get("personal_memories", [])),
                    "collective": len(row.get("collective_memories", [])),
                    "failures": len(row.get("failure_schedule", [])),
                },
                sort_keys=True,
            )
            for row in environments[split].values()
        )
        split_reports[split] = {
            "total_tasks": len(tasks),
            "unique_task_text": len({str(task["user_request"]) for task in tasks}),
            "normalized_template_clusters": summarize_counts(normalized),
            "semantic_template_clusters": summarize_counts(semantic),
            "source_groups": summarize_counts(source_groups),
            "language_distribution": dict(Counter(str(task["language"]) for task in tasks)),
            "difficulty_distribution": dict(Counter(str(task["difficulty"]) for task in tasks)),
            "tool_combinations": dict(Counter("+".join(sorted(task.get("available_tools", []))) for task in tasks)),
            "objective_modes": dict(
                Counter(str(graders[split][str(task["task_id"])].get("objective", {}).get("mode")) for task in tasks)
            ),
            "environment_shapes": summarize_counts(environment_shapes),
            "citation_required_ratio": round(
                sum(
                    any(
                        bool(claim.get("citation_required", True))
                        for claim in graders[split][str(task["task_id"])].get("evidence", {}).get("claims", [])
                    )
                    for task in tasks
                )
                / len(tasks),
                6,
            ),
            "state_based_ratio": round(
                sum(graders[split][str(task["task_id"])].get("objective", {}).get("mode") == "state" for task in tasks)
                / len(tasks),
                6,
            ),
            "abstention_ratio": round(
                sum(
                    graders[split][str(task["task_id"])].get("objective", {}).get("mode") == "abstain" for task in tasks
                )
                / len(tasks),
                6,
            ),
        }
    material_reuse = {
        split: summarize_counts(
            Counter(str(row.get("material_id")) for row in corpora.get(split, []) if row.get("material_id") is not None)
        )
        for split in ("regression", "development", "sealed")
    }
    fixture_family = Counter()
    origin = Counter()
    for rows in environments.values():
        for row in rows.values():
            fixture_family.update(
                key
                for key in ("web_pages", "personal_memories", "collective_memories", "failure_schedule")
                if row.get(key)
            )
            origin.update(
                [
                    "synthetic_fixture"
                    if any(row.get(key) for key in ("web_pages", "personal_memories", "collective_memories"))
                    else "authentic_or_state"
                ]
            )
    report = {
        "schema_version": "studyhub.agentbench-v1-semantic-audit.v1",
        "benchmark_version": "studyhub-agentbench-v1",
        "generated_at": artifact_timestamp(),
        "public_manifest_sha256": sha256(public_root / "manifest.json"),
        "splits": split_reports,
        "material_reuse": material_reuse,
        "fixture_families": dict(fixture_family),
        "origin_proxy": dict(origin),
        "teacher_review_implementation": "deterministic_contract_check_not_semantic_review",
        "known_measurement_defects": [
            "direct_answer_prompts_disclose_the_no_tool_policy",
            "query_rewrite_does_not_require_query_change_or_evidence_gain",
            "permission_recovery_requires_an_acl_probe",
            "difficulty_is_ordinal_rotation",
            "horizon_is_budget_label_not_realized_policy_depth",
            "rubric_mode_uses_concept_substring_matching",
            "development_and_sealed_share_scenario_factory",
            "retrieval_backend_is_bm25_not_hybrid",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dev = split_reports["development"]
    markdown = f"""# StudyHub AgentBench v1 Semantic Audit

Generated: `{report["generated_at"]}`
Frozen manifest: `{report["public_manifest_sha256"]}`

This audit does not modify Benchmark v1. It quantifies why the frozen benchmark remains useful for runtime lineage but is not reused as the formal v2 capability ruler.

## Development split

- Tasks: **{dev["total_tasks"]}**
- Source groups: **{dev["source_groups"]["unique"]}**; max reuse **{dev["source_groups"]["max"]}**; p90 **{dev["source_groups"]["p90"]}**
- Normalized template clusters: **{dev["normalized_template_clusters"]["unique"]}**; largest share **{dev["normalized_template_clusters"]["largest_share"]:.2%}**
- Semantic shape clusters: **{dev["semantic_template_clusters"]["unique"]}**; largest share **{dev["semantic_template_clusters"]["largest_share"]:.2%}**
- Material corpus groups: **{material_reuse["development"]["unique"]}**

## Blocking interpretation issues

The prior `teacher review` was a deterministic contract checker, not an independent semantic review. Direct-answer prompts disclosed the desired policy, query-rewrite recovery did not require a changed query, ACL recovery required a denial, difficulty came from ordinal rotation, and the internal replay backend was BM25 rather than Hybrid RAG.

## Disposition

Benchmark v1 is immutable historical evidence. Benchmark v2 uses source-group/template-separated splits, `UNSCORED` initial difficulty, explicit source origin, cluster-aware statistics, semantic review status, and separate deterministic versus semantic evaluator layers.
"""
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(markdown, encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-root", type=Path, default=project / "benchmarks/studyhub-agent-v1")
    parser.add_argument("--hidden-root", type=Path, default=project / "artifacts/benchmark-v1/studyhub-agent-v1")
    parser.add_argument("--output", type=Path, default=project / "artifacts/benchmark-v2/audits/v1-semantic-audit.json")
    parser.add_argument("--markdown", type=Path, default=project / "docs/benchmark/v1-semantic-audit.md")
    return parser.parse_args()


def main() -> int:
    report = audit(parse_args())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
