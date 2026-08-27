#!/usr/bin/env python3
"""Fail-closed structural, provenance, leakage and reachability audit for AgentBench v2."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v1.tool_contracts import TOOL_SCHEMAS
from studyhub_agent.benchmark_v2.schema import (
    BENCHMARK_VERSION,
    GRADER_SCHEMA_VERSION,
    BenchmarkTaskV2,
    artifact_timestamp,
    load_jsonl,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def source_texts(environment: dict[str, Any], corpus: dict[str, dict[str, Any]]) -> dict[str, str]:
    values = {
        source_id: " ".join(str(row.get(key, "")) for key in ("title", "text", "content", "snippet"))
        for source_id, row in corpus.items()
    }
    for field in ("inline_documents", "web_pages", "personal_memories", "collective_memories"):
        for row in environment.get(field, []):
            values[str(row["source_id"])] = " ".join(
                str(row.get(key, "")) for key in ("title", "text", "content", "snippet")
            )
    return values


def normalized_evidence(value: str) -> str:
    return re.sub(r"[^0-9a-z㐀-鿿]+", " ", value.casefold()).strip()


class Audit:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def record(self, name: str, passed: bool, detail: Any) -> None:
        self.checks.append({"name": name, "passed": passed, "detail": detail})

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [row for row in self.checks if not row["passed"]]


def audit(args: argparse.Namespace) -> dict[str, Any]:
    public_root = args.public_root.resolve()
    hidden_root = args.hidden_root.resolve()
    manifest = json.loads((public_root / "manifest.json").read_text(encoding="utf-8"))
    split_paths = {
        "regression": public_root / "regression/tasks.jsonl",
        "development": public_root / "development/tasks.jsonl",
        "calibration_challenge": public_root / "calibration_challenge/tasks.jsonl",
        "sealed_a": hidden_root / "tasks/sealed_a.jsonl",
        "sealed_b": hidden_root / "tasks/sealed_b.jsonl",
    }
    tasks = {split: load_jsonl(path) for split, path in split_paths.items()}
    environments = {
        split: {str(row["task_id"]): row for row in load_jsonl(hidden_root / f"environments/{split}.jsonl")}
        for split in split_paths
    }
    graders = {
        split: {str(row["task_id"]): row for row in load_jsonl(hidden_root / f"graders/{split}.jsonl")}
        for split in split_paths
    }
    corpora = {
        split: {str(row["source_id"]): row for row in load_jsonl(hidden_root / f"corpora/{split}.jsonl")}
        for split in split_paths
    }
    result = Audit()
    result.record(
        "benchmark_version", manifest.get("benchmark_version") == BENCHMARK_VERSION, manifest.get("benchmark_version")
    )
    all_ids = [str(row["task_id"]) for rows in tasks.values() for row in rows]
    result.record(
        "task_ids_globally_unique",
        len(all_ids) == len(set(all_ids)),
        {"total": len(all_ids), "unique": len(set(all_ids))},
    )
    schema_errors = []
    bijection_errors = []
    for split, rows in tasks.items():
        for row in rows:
            try:
                BenchmarkTaskV2.from_dict(row)
            except Exception as error:  # noqa: BLE001 - report all candidate errors
                schema_errors.append(f"{row.get('task_id')}: {error}")
        ids = {str(row["task_id"]) for row in rows}
        if ids != set(environments[split]) or ids != set(graders[split]):
            bijection_errors.append(split)
    result.record("public_task_schema", not schema_errors, schema_errors[:20])
    result.record("task_environment_grader_bijection", not bijection_errors, bijection_errors)

    source_group_splits: dict[str, set[str]] = {}
    source_group_counts: Counter[str] = Counter()
    rag_group_counts: Counter[str] = Counter()
    semantic_cluster_splits: dict[str, set[str]] = {}
    exact_requests = []
    for split, rows in tasks.items():
        for row in rows:
            source_group = str(row["source_group_id"])
            source_group_splits.setdefault(source_group, set()).add(split)
            source_group_counts[source_group] += 1
            if row["environment_origin"] == "authentic_studyhub_preview":
                rag_group_counts[source_group] += 1
            cluster = str(row["semantic_template_cluster"])
            semantic_cluster_splits.setdefault(cluster, set()).add(split)
            exact_requests.append(str(row["user_request"]))
    source_overlap = {key: sorted(value) for key, value in source_group_splits.items() if len(value) > 1}
    template_overlap = {key: sorted(value) for key, value in semantic_cluster_splits.items() if len(value) > 1}
    result.record("cross_split_source_group_overlap", not source_overlap, source_overlap)
    result.record("cross_split_declared_template_overlap", not template_overlap, template_overlap)
    result.record(
        "source_group_reuse_at_most_five",
        max(source_group_counts.values(), default=0) <= 5,
        source_group_counts.most_common(10),
    )
    result.record(
        "authentic_rag_group_reuse_at_most_three",
        max(rag_group_counts.values(), default=0) <= 3,
        rag_group_counts.most_common(10),
    )
    result.record(
        "exact_request_duplicates",
        len(exact_requests) == len(set(exact_requests)),
        len(exact_requests) - len(set(exact_requests)),
    )
    development_clusters = Counter(str(row["semantic_template_cluster"]) for row in tasks["development"])
    largest_declared_share = max(development_clusters.values(), default=0) / max(1, len(tasks["development"]))
    result.record(
        "development_declared_cluster_concentration",
        largest_declared_share <= 0.02,
        {"largest_share": largest_declared_share, "largest": development_clusters.most_common(5)},
    )

    origin_counts = Counter(str(row["environment_origin"]) for rows in tasks.values() for row in rows)
    authentic = sum(value for key, value in origin_counts.items() if key.startswith("authentic_"))
    total = sum(origin_counts.values())
    result.record(
        "authentic_source_task_ratio",
        authentic / total >= 0.60,
        {"authentic": authentic, "total": total, "ratio": authentic / total, "origins": dict(origin_counts)},
    )
    result.record(
        "initial_difficulty_is_unscored",
        all(row["difficulty"] == "UNSCORED" for rows in tasks.values() for row in rows),
        dict(Counter(str(row["difficulty"]) for rows in tasks.values() for row in rows)),
    )

    grader_errors = []
    unreachable = []
    process_overconstraints = []
    allowed_process = {
        "query_reformulation": "query_reformulation",
        "permission_avoidance": "permission_avoidance",
        "permission_recovery": "permission_recovery",
        "tool_failure_recovery": "failure_recovery",
    }
    for split, rows in tasks.items():
        for task in rows:
            task_id = str(task["task_id"])
            environment = environments[split][task_id]
            grader = graders[split][task_id]
            if grader.get("schema_version") != GRADER_SCHEMA_VERSION:
                grader_errors.append(f"{task_id}:schema")
            if list(task["available_tools"]) != list(environment.get("available_tools", [])):
                grader_errors.append(f"{task_id}:tools")
            unknown_tools = set(task["available_tools"]) - set(TOOL_SCHEMAS)
            if unknown_tools:
                grader_errors.append(f"{task_id}:unknown:{sorted(unknown_tools)}")
            process_mode = str(
                grader.get("evaluation_contract", {}).get("process_constraints", {}).get("mode", "open_path")
            )
            expected_mode = allowed_process.get(str(task["capability_id"]), "open_path")
            if process_mode != expected_mode:
                process_overconstraints.append(f"{task_id}:{process_mode}!={expected_mode}")
            sources = source_texts(environment, corpora[split])
            for claim in grader.get("claims", []):
                ids = list(map(str, claim.get("support_source_ids", [])))
                if not ids or any(source_id not in sources for source_id in ids):
                    unreachable.append(f"{task_id}:{claim.get('claim_id')}:missing-source")
                    continue
                support = normalized_evidence(" ".join(sources[source_id] for source_id in ids))
                spans = [str(value).strip() for value in claim.get("support_spans", [])]
                if not spans or not all(normalized_evidence(span) in support for span in spans):
                    unreachable.append(f"{task_id}:{claim.get('claim_id')}:span")
                facts = [str(value).strip() for value in claim.get("support_facts", [])]
                if not facts or not all(normalized_evidence(value) in support for value in facts):
                    unreachable.append(f"{task_id}:{claim.get('claim_id')}:fact")
    result.record("grader_and_tool_contracts", not grader_errors, grader_errors[:20])
    result.record("deterministic_claim_reachability", not unreachable, unreachable[:30])
    result.record(
        "process_constraints_are_capability_specific", not process_overconstraints, process_overconstraints[:20]
    )

    evaluator_files = [
        args.project / "src/studyhub_agent/benchmark_v2/development_evaluator.py",
        args.project / "src/studyhub_agent/benchmark_v2/sealed_evaluator.py",
        args.project / "src/studyhub_agent/benchmark_v2/evaluator_core.py",
    ]
    imports = {str(path.relative_to(args.project)): sorted(imported_modules(path)) for path in evaluator_files}
    forbidden_imports = {
        path: [name for name in names if name.startswith("training") or ".reward" in name]
        for path, names in imports.items()
    }
    forbidden_imports = {path: names for path, names in forbidden_imports.items() if names}
    result.record("evaluator_training_reward_isolation", not forbidden_imports, forbidden_imports or imports)

    lock = json.loads((args.project / "configs/benchmark-v1-frozen-hashes.json").read_text(encoding="utf-8"))
    v1_mismatches = {
        path: {"expected": expected, "actual": sha256(args.project / path)}
        for path, expected in lock["files"].items()
        if not (args.project / path).is_file() or sha256(args.project / path) != expected
    }
    result.record("benchmark_v1_frozen_integrity", not v1_mismatches, v1_mismatches)
    manifest_hash_errors = []
    for relative, expected in manifest.get("public_files", {}).items():
        path = public_root / relative
        if not path.is_file() or sha256(path) != expected:
            manifest_hash_errors.append(relative)
    for relative, expected in manifest.get("hidden_files", {}).items():
        path = hidden_root / relative
        if not path.is_file() or sha256(path) != expected:
            manifest_hash_errors.append(f"hidden:{relative}")
    result.record("manifest_asset_hashes", not manifest_hash_errors, manifest_hash_errors)

    report = {
        "schema_version": "studyhub.agentbench-structural-audit.v2",
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": artifact_timestamp(),
        "status": "PASS" if not result.failures else "FAIL",
        "summary": {
            "checks": len(result.checks),
            "passed": len(result.checks) - len(result.failures),
            "failed": len(result.failures),
        },
        "checks": result.checks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: report[key] for key in ("schema_version", "benchmark_version", "generated_at", "status", "summary")}
    summary["audit_sha256"] = sha256(args.output)
    args.public_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=project)
    parser.add_argument("--public-root", type=Path, default=project / "benchmarks/studyhub-agent-v2")
    parser.add_argument("--hidden-root", type=Path, default=project / "artifacts/benchmark-v2/studyhub-agent-v2")
    parser.add_argument("--output", type=Path, default=project / "artifacts/benchmark-v2/audits/structural-audit.json")
    parser.add_argument(
        "--public-summary", type=Path, default=project / "benchmarks/studyhub-agent-v2/structural-audit-summary.json"
    )
    return parser.parse_args()


def main() -> int:
    report = audit(parse_args())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
