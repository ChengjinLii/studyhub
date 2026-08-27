#!/usr/bin/env python3
"""Deterministic lexical/structural diversity audit for AgentBench v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v2.schema import BENCHMARK_VERSION, load_jsonl

_QUOTED = re.compile(r"[\"'“”‘’《》][^\"'“”‘’《》]{1,120}[\"'“”‘’《》]")
_DATE = re.compile(r"\b(?:19|20)\d{2}(?:[-/.年]\d{1,2})?(?:[-/.月]\d{1,2})?日?\b")
_HASH_OR_ID = re.compile(r"(?:v2:|shb-v2-|[a-z-]+:)?[a-f0-9-]{6,}|\b\d+\b", re.I)
_SLOT_WORDS = re.compile(
    r"(?i)(?:course|material|topic|marker|token|资料|课程|主题|标记|日期|地点|分数|分钟)\s*[:：]?\s*\S+"
)


def normalize(value: str) -> str:
    value = value.casefold()
    value = _QUOTED.sub(" <ENTITY> ", value)
    value = _DATE.sub(" <DATE> ", value)
    value = _HASH_OR_ID.sub(" <ID> ", value)
    value = _SLOT_WORDS.sub(" <SLOT> ", value)
    value = re.sub(r"[^a-z0-9\u3400-\u9fff<>]+", " ", value)
    return " ".join(value.split())


def token_set(value: str) -> set[str]:
    normalized = normalize(value)
    latin = re.findall(r"[a-z0-9<>]+", normalized)
    chinese = re.findall(r"[\u3400-\u9fff]+", normalized)
    bigrams = [run[index : index + 2] for run in chinese for index in range(max(0, len(run) - 1))]
    return set(latin + bigrams)


def similarity(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left or right else 1.0


def clusters(rows: list[dict[str, Any]], threshold: float = 0.82) -> list[list[int]]:
    parents = list(range(len(rows)))
    tokens = [token_set(str(row["user_request"])) for row in rows]

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parents[b] = a

    for left in range(len(rows)):
        for right in range(left + 1, len(rows)):
            if rows[left]["capability_id"] != rows[right]["capability_id"]:
                continue
            if similarity(tokens[left], tokens[right]) >= threshold:
                union(left, right)
    grouped: dict[int, list[int]] = defaultdict(list)
    for index in range(len(rows)):
        grouped[find(index)].append(index)
    return list(grouped.values())


def audit(args: argparse.Namespace) -> dict[str, Any]:
    public_root = args.public_root.resolve()
    hidden_root = args.hidden_root.resolve()
    paths = {
        "regression": public_root / "regression/tasks.jsonl",
        "development": public_root / "development/tasks.jsonl",
        "calibration_challenge": public_root / "calibration_challenge/tasks.jsonl",
        "sealed_a": hidden_root / "tasks/sealed_a.jsonl",
        "sealed_b": hidden_root / "tasks/sealed_b.jsonl",
    }
    tasks = {split: load_jsonl(path) for split, path in paths.items()}
    graders = {
        split: {str(row["task_id"]): row for row in load_jsonl(hidden_root / f"graders/{split}.jsonl")}
        for split in paths
    }
    split_report = {}
    normalized_by_split = {}
    declared_by_split = {}
    for split, rows in tasks.items():
        normalized = [normalize(str(row["user_request"])) for row in rows]
        normalized_by_split[split] = set(normalized)
        declared_by_split[split] = {str(row["semantic_template_cluster"]) for row in rows}
        semantic = clusters(rows)
        semantic_sizes = sorted((len(group) for group in semantic), reverse=True)
        answers = Counter(
            hashlib.sha256(
                json.dumps(graders[split][str(row["task_id"])].get("outcome", {}), sort_keys=True).encode()
            ).hexdigest()[:16]
            for row in rows
        )
        tool_paths = Counter("+".join(sorted(row.get("available_tools", []))) for row in rows)
        environment_shapes = Counter(
            json.dumps(
                {
                    "origin": row["environment_origin"],
                    "tools": sorted(row.get("available_tools", [])),
                    "features": row.get("difficulty_features", {}),
                },
                sort_keys=True,
            )
            for row in rows
        )
        split_report[split] = {
            "tasks": len(rows),
            "exact_duplicates": len(rows) - len({str(row["user_request"]) for row in rows}),
            "normalized_duplicates": len(rows) - len(set(normalized)),
            "declared_template_clusters": len(declared_by_split[split]),
            "lexical_semantic_clusters": len(semantic),
            "largest_semantic_cluster": semantic_sizes[0] if semantic_sizes else 0,
            "largest_semantic_cluster_share": semantic_sizes[0] / len(rows) if rows else 0.0,
            "source_group_concentration": Counter(str(row["source_group_id"]) for row in rows).most_common(10),
            "same_answer_concentration": answers.most_common(10),
            "same_tool_path_concentration": tool_paths.most_common(10),
            "same_environment_shape_concentration": environment_shapes.most_common(10),
            "language_distribution": dict(Counter(str(row["language"]) for row in rows)),
            "origin_distribution": dict(Counter(str(row["environment_origin"]) for row in rows)),
            "capability_distribution": dict(Counter(str(row["capability_id"]) for row in rows)),
            "difficulty_feature_distribution": {
                key: dict(Counter(str(row["difficulty_features"][key]) for row in rows))
                for key in rows[0]["difficulty_features"]
            }
            if rows
            else {},
        }
    normalized_overlap = {}
    declared_overlap = {}
    names = list(paths)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            common_normalized = normalized_by_split[left] & normalized_by_split[right]
            common_declared = declared_by_split[left] & declared_by_split[right]
            if common_normalized:
                normalized_overlap[f"{left}|{right}"] = len(common_normalized)
            if common_declared:
                declared_overlap[f"{left}|{right}"] = len(common_declared)
    dev = split_report["development"]
    checks = {
        "exact_duplicates_zero": all(row["exact_duplicates"] == 0 for row in split_report.values()),
        "cross_split_normalized_duplicates_zero": not normalized_overlap,
        "cross_split_declared_clusters_zero": not declared_overlap,
        "largest_semantic_cluster_at_most_two_percent_dev": dev["largest_semantic_cluster_share"] <= 0.02,
    }
    report = {
        "schema_version": "studyhub.agentbench-semantic-diversity-audit.v2",
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "method": {
            "normalization": "entity/date/id/slot replacement plus mixed Chinese bigram and Latin token sets",
            "clustering": "capability-scoped connected components at Jaccard >= 0.82",
            "online_embedding_dependency": False,
        },
        "checks": checks,
        "cross_split_normalized_overlap": normalized_overlap,
        "cross_split_declared_overlap": declared_overlap,
        "splits": split_report,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "schema_version": report["schema_version"],
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": report["generated_at"],
        "status": report["status"],
        "checks": checks,
        "development": {
            "tasks": dev["tasks"],
            "semantic_clusters": dev["lexical_semantic_clusters"],
            "largest_cluster": dev["largest_semantic_cluster"],
            "largest_cluster_share": dev["largest_semantic_cluster_share"],
        },
        "audit_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }
    args.public_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-root", type=Path, default=project / "benchmarks/studyhub-agent-v2")
    parser.add_argument("--hidden-root", type=Path, default=project / "artifacts/benchmark-v2/studyhub-agent-v2")
    parser.add_argument(
        "--output", type=Path, default=project / "artifacts/benchmark-v2/audits/semantic-diversity.json"
    )
    parser.add_argument(
        "--public-summary", type=Path, default=project / "benchmarks/studyhub-agent-v2/semantic-audit-summary.json"
    )
    return parser.parse_args()


def main() -> int:
    report = audit(parse_args())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
