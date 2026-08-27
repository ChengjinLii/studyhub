#!/usr/bin/env python3
"""Fail-closed structural, reachability and contamination audit for Benchmark v1."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v1.schema import (
    BENCHMARK_VERSION,
    PUBLIC_FORBIDDEN_FIELDS,
    BenchmarkTask,
    load_jsonl,
)
from studyhub_agent.benchmark_v1.tool_contracts import TOOL_SCHEMAS

HIDDEN_PATH_FIELDS = {
    "expected_call",
    "expected_calls",
    "gold_query",
    "gold_source_order",
    "gold_trajectory",
    "supporting_facts",
}

LOW_QUALITY_TITLE = re.compile(r"(?i)(?:^|\b)(?:sample|test|demo)(?:\b|$)|测试|示例")
UNREDACTED_CONTACT = re.compile(
    r"(?i)(?:QQ\s*[:：号]?\s*\d{5,}|(?:微信|wechat)\s*[:：号]?\s*[A-Za-z0-9_-]{4,}|(?<!\d)1[3-9]\d{9}(?!\d))"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def nested_keys(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        result.update(map(str, value))
        for nested in value.values():
            result.update(nested_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            result.update(nested_keys(nested))
    return result


def normalized_request(value: str) -> str:
    value = re.sub(r"\d+", "<N>", value.casefold())
    value = re.sub(r"[a-f0-9]{8,}", "<HASH>", value)
    return " ".join(value.split())


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


class Audit:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def record(self, name: str, passed: bool, detail: Any) -> None:
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            self.errors.append(f"{name}: {detail}")

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _source_store(
    environment: dict[str, Any],
    corpora: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, str]:
    values: dict[str, str] = {}
    corpus_id = str(environment.get("corpus_id", ""))
    for source_id, row in corpora.get(corpus_id, {}).items():
        values[source_id] = " ".join(str(row.get(key, "")) for key in ("title", "text", "tags"))
    for row in environment.get("inline_documents", []):
        values[str(row["source_id"])] = " ".join(str(row.get(key, "")) for key in ("title", "text", "tags"))
    for row in environment.get("web_pages", []):
        values[str(row["source_id"])] = " ".join(
            str(row.get(key, "")) for key in ("title", "snippet", "content", "keywords")
        )
    for key in ("personal_memories", "collective_memories"):
        for row in environment.get(key, []):
            values[str(row["source_id"])] = " ".join(
                str(row.get(name, "")) for name in ("title", "content", "tags", "course")
            )
    return values


def audit(args: argparse.Namespace) -> dict[str, Any]:
    project = args.project.resolve()
    public_root = args.public_root.resolve()
    hidden_root = args.hidden_root.resolve()
    matrix = json.loads(args.capability_matrix.read_text(encoding="utf-8"))
    capability_ids = [str(row["id"]) for row in matrix["capabilities"]]
    expected_counts = {
        "regression": {capability_id: 8 for capability_id in capability_ids},
        "development": {str(row["id"]): int(row["development_tasks"]) for row in matrix["capabilities"]},
        "sealed": {str(row["id"]): int(row["sealed_tasks"]) for row in matrix["capabilities"]},
    }
    task_paths = {
        "regression": public_root / "regression/tasks.jsonl",
        "development": public_root / "development/tasks.jsonl",
        "sealed": hidden_root / "tasks/sealed.jsonl",
    }
    tasks = {split: load_jsonl(path) for split, path in task_paths.items()}
    environments = {
        split: {str(row["task_id"]): row for row in load_jsonl(hidden_root / "environments" / f"{split}.jsonl")}
        for split in task_paths
    }
    graders = {
        split: {str(row["task_id"]): row for row in load_jsonl(hidden_root / "graders" / f"{split}.jsonl")}
        for split in task_paths
    }
    corpora = {}
    for path in (hidden_root / "corpora").glob("*.jsonl"):
        corpora[path.stem] = {str(row["source_id"]): row for row in load_jsonl(path)}

    result = Audit()
    all_task_ids = [str(row["task_id"]) for rows in tasks.values() for row in rows]
    result.record(
        "task_ids_globally_unique",
        len(all_task_ids) == len(set(all_task_ids)),
        {"total": len(all_task_ids), "unique": len(set(all_task_ids))},
    )
    for split, rows in tasks.items():
        parsed = []
        parse_errors = []
        for row in rows:
            try:
                parsed.append(BenchmarkTask.from_dict(row))
            except Exception as error:  # noqa: BLE001 - aggregate all dataset errors
                parse_errors.append(f"{row.get('task_id')}: {error}")
        result.record(f"{split}_public_schema", not parse_errors, parse_errors[:10])
        counts = Counter(task.capability_id for task in parsed)
        result.record(
            f"{split}_capability_quota",
            counts == Counter(expected_counts[split]),
            {"actual": dict(counts), "expected": expected_counts[split]},
        )
        task_ids = {task.task_id for task in parsed}
        result.record(
            f"{split}_task_environment_bijection",
            task_ids == set(environments[split]),
            {
                "task_only": sorted(task_ids - set(environments[split]))[:5],
                "environment_only": sorted(set(environments[split]) - task_ids)[:5],
            },
        )
        result.record(
            f"{split}_task_grader_bijection",
            task_ids == set(graders[split]),
            {
                "task_only": sorted(task_ids - set(graders[split]))[:5],
                "grader_only": sorted(set(graders[split]) - task_ids)[:5],
            },
        )
        exact_requests = [task.user_request for task in parsed]
        result.record(
            f"{split}_exact_request_uniqueness",
            len(exact_requests) == len(set(exact_requests)),
            {"total": len(exact_requests), "unique": len(set(exact_requests))},
        )
        shapes = Counter(normalized_request(value) for value in exact_requests)
        largest_shape = max(shapes.values(), default=0)
        result.record(
            f"{split}_near_template_concentration",
            largest_shape <= max(8, int(len(rows) * 0.03)),
            {
                "normalized_shapes": len(shapes),
                "largest_cluster": largest_shape,
                "largest_allowed": max(8, int(len(rows) * 0.03)),
            },
        )
        hidden_public_keys = sorted(set().union(*(nested_keys(row) for row in rows)) & PUBLIC_FORBIDDEN_FIELDS)
        result.record(f"{split}_oracle_isolation", not hidden_public_keys, hidden_public_keys)

    grader_path_leaks = []
    unreachable_claims = []
    invalid_environment_tools = []
    missing_failure_contracts = []
    state_contract_errors = []
    process_contract_errors = []
    required_family_counts = {
        "rag_to_web_fallback": 2,
        "rag_memory_composition": 2,
        "web_memory_composition": 2,
        "long_horizon": 4,
        "deep_research": 4,
    }
    for split, rows in tasks.items():
        for task in rows:
            task_id = str(task["task_id"])
            environment = environments[split][task_id]
            grader = graders[split][task_id]
            leak = nested_keys(grader) & HIDDEN_PATH_FIELDS
            if leak:
                grader_path_leaks.append({"task_id": task_id, "keys": sorted(leak)})
            declared_tools = list(map(str, environment.get("available_tools", [])))
            if declared_tools != list(map(str, task.get("available_tools", []))):
                invalid_environment_tools.append(f"{task_id}: public/environment mismatch")
            unknown = set(declared_tools) - set(TOOL_SCHEMAS)
            if unknown:
                invalid_environment_tools.append(f"{task_id}: unknown {sorted(unknown)}")
            for failure in environment.get("failure_schedule", []):
                if str(failure.get("tool")) not in declared_tools:
                    missing_failure_contracts.append(task_id)
            capability = str(task["capability_id"])
            if capability in {"query_rewrite", "tool_failure_recovery"} and not environment.get("failure_schedule"):
                missing_failure_contracts.append(task_id)
            if capability == "permission_recovery" and not any(
                str(row.get("access_scope")) in {"private", "paid"} for row in environment.get("inline_documents", [])
            ):
                missing_failure_contracts.append(task_id)
            if grader.get("objective", {}).get("mode") == "state" and not (
                set(declared_tools) & {"study_plan_update", "material_bookmark_add", "learning_progress_record"}
            ):
                state_contract_errors.append(task_id)
            process = grader.get("process", {})
            if capability != "direct_answer_abstention" and int(process.get("min_useful_tool_calls", 0)) < 1:
                process_contract_errors.append(f"{task_id}:minimum_useful_calls")
            expected_families = required_family_counts.get(capability, 0)
            if len(process.get("required_tool_families", [])) < expected_families:
                process_contract_errors.append(f"{task_id}:required_tool_families")
            if capability in {"query_rewrite", "tool_failure_recovery"} and not (
                process.get("required_environment_errors") and process.get("require_recovery_after_error") is True
            ):
                process_contract_errors.append(f"{task_id}:failure_recovery")
            if capability == "permission_recovery" and not (
                process.get("require_permission_denial") is True
                and process.get("require_recovery_after_error") is True
            ):
                process_contract_errors.append(f"{task_id}:permission_recovery")
            sources = _source_store(environment, corpora)
            for hidden_claim in grader.get("evidence", {}).get("claims", []):
                source_ids = list(map(str, hidden_claim.get("support_source_ids", [])))
                if not source_ids or any(source_id not in sources for source_id in source_ids):
                    unreachable_claims.append(
                        {"task_id": task_id, "claim_id": hidden_claim.get("claim_id"), "reason": "missing_source"}
                    )
                    continue
                combined = " ".join(sources[source_id] for source_id in source_ids).casefold()
                for group in hidden_claim.get("concept_groups", []):
                    if not any(str(option).casefold() in combined for option in group):
                        unreachable_claims.append(
                            {
                                "task_id": task_id,
                                "claim_id": hidden_claim.get("claim_id"),
                                "reason": "concept_not_in_support",
                                "group": group,
                            }
                        )
    result.record("grader_has_no_gold_path_fields", not grader_path_leaks, grader_path_leaks[:10])
    result.record("claim_support_is_reachable", not unreachable_claims, unreachable_claims[:20])
    result.record("environment_tool_contracts", not invalid_environment_tools, invalid_environment_tools[:20])
    result.record("failure_and_acl_contracts", not missing_failure_contracts, missing_failure_contracts[:20])
    result.record("state_postcondition_contracts", not state_contract_errors, state_contract_errors[:20])
    result.record("capability_process_contracts", not process_contract_errors, process_contract_errors[:20])

    corpus_quality_errors = []
    for corpus_id, rows in corpora.items():
        for source_id, row in rows.items():
            title = str(row.get("title", ""))
            text = str(row.get("text", ""))
            if LOW_QUALITY_TITLE.search(title):
                corpus_quality_errors.append(f"{corpus_id}:{source_id}:low_quality_title")
            if UNREDACTED_CONTACT.search(f"{title}\n{text}"):
                corpus_quality_errors.append(f"{corpus_id}:{source_id}:unredacted_contact")
    result.record("corpus_source_quality", not corpus_quality_errors, corpus_quality_errors[:20])

    partition_ids = {name: {int(row["material_id"]) for row in values.values()} for name, values in corpora.items()}
    overlaps = {}
    names = sorted(partition_ids)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            common = sorted(partition_ids[left] & partition_ids[right])
            if common:
                overlaps[f"{left}|{right}"] = common
    result.record("material_partition_isolation", not overlaps, overlaps)

    development_path = project / "src/studyhub_agent/benchmark_v1/development_evaluator.py"
    sealed_path = project / "src/studyhub_agent/benchmark_v1/sealed_evaluator.py"
    development_imports = imported_modules(development_path)
    sealed_imports = imported_modules(sealed_path)
    result.record(
        "development_evaluator_training_isolation",
        not any(name.startswith("training") or ".reward" in name for name in development_imports),
        sorted(development_imports),
    )
    result.record(
        "sealed_evaluator_code_isolation",
        not any(
            name.startswith("training") or "development_evaluator" in name or ".reward" in name
            for name in sealed_imports
        ),
        sorted(sealed_imports),
    )
    ignored = (
        subprocess.run(
            ["git", "check-ignore", "-q", str(hidden_root)],
            cwd=project,
            check=False,
        ).returncode
        == 0
    )
    result.record("sealed_assets_git_ignored", ignored, str(hidden_root))

    manifest = json.loads((public_root / "manifest.json").read_text(encoding="utf-8"))
    stale_files = []
    for relative, expected in manifest.get("public_files", {}).items():
        path = public_root / relative
        if not path.is_file() or sha256(path) != expected:
            stale_files.append(relative)
    for relative, expected in manifest.get("hidden_files", {}).items():
        path = hidden_root / relative
        if not path.is_file() or sha256(path) != expected:
            stale_files.append(f"hidden:{relative}")
    result.record("manifest_file_hashes", not stale_files, stale_files[:20])
    result.record(
        "benchmark_version_consistency",
        manifest.get("benchmark_version") == BENCHMARK_VERSION,
        manifest.get("benchmark_version"),
    )

    report = {
        "schema_version": "studyhub.agentbench-structural-audit.v1",
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": "PASS" if not result.errors else "FAIL",
        "checks": result.checks,
        "errors": result.errors,
        "warnings": result.warnings,
        "summary": {
            "checks": len(result.checks),
            "passed": sum(bool(row["passed"]) for row in result.checks),
            "failed": sum(not bool(row["passed"]) for row in result.checks),
            "tasks": {split: len(rows) for split, rows in tasks.items()},
            "capabilities": len(capability_ids),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    public_summary = {
        "schema_version": report["schema_version"],
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": report["generated_at"],
        "status": report["status"],
        "summary": report["summary"],
        "audit_sha256": sha256(args.output),
        "hidden_details": "artifacts/benchmark-v1/studyhub-agent-v1/audits/structural-audit.json",
    }
    summary_path = public_root / "structural-audit-summary.json"
    summary_path.write_text(
        json.dumps(public_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=project)
    parser.add_argument(
        "--public-root",
        type=Path,
        default=project / "benchmarks/studyhub-agent-v1",
    )
    parser.add_argument(
        "--hidden-root",
        type=Path,
        default=project / "artifacts/benchmark-v1/studyhub-agent-v1",
    )
    parser.add_argument(
        "--capability-matrix",
        type=Path,
        default=project / "configs/program-v3/capability-matrix-v1.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project / "artifacts/benchmark-v1/studyhub-agent-v1/audits/structural-audit.json",
    )
    return parser.parse_args()


def main() -> int:
    report = audit(parse_args())
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if report["errors"]:
        for error in report["errors"]:
            print(f"ERROR: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
