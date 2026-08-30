#!/usr/bin/env python3
"""Fail closed when Teacher-to-Hermes task contracts are not executable."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for entry in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from training.rl.frozen_environment import FrozenTaskEnvironment  # noqa: E402

FORBIDDEN_PUBLIC_FIELDS = {
    "allowed_citations",
    "expected_tool_names",
    "fixtures",
    "gold_answer",
    "gold_tool_path",
    "hidden_oracle",
    "reference_final",
    "required_observation_markers",
    "verifier",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def nested_values(value: Any, key: str) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        item = value.get(key)
        if isinstance(item, str) and item:
            result.add(item)
        for child in value.values():
            result.update(nested_values(child, key))
    elif isinstance(value, list):
        for child in value:
            result.update(nested_values(child, key))
    return result


def evidence_source_ids(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        source_id = value.get("source_id")
        text = value.get("text")
        if isinstance(source_id, str) and source_id and isinstance(text, str) and text.strip():
            result.add(source_id)
        for child in value.values():
            result.update(evidence_source_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(evidence_source_ids(child))
    return result


def _record(errors: list[dict[str, Any]], task_id: str, code: str, **details: Any) -> None:
    errors.append({"task_id": task_id, "code": code, **details})


def _execute_route(
    environment: dict[str, Any],
    fixture: dict[str, Any],
    route: dict[str, Any],
) -> dict[str, Any]:
    runtime = FrozenTaskEnvironment(environment, fixture)
    raw = asyncio.run(runtime.execute(str(route["name"]), dict(route.get("arguments", {}))))
    return {
        "response": json.loads(raw),
        "errors": list(runtime.trace.error_codes),
        "read_source_ids": sorted(runtime.trace.read_source_ids),
    }


def audit_root(root: Path) -> dict[str, Any]:
    tasks_path = root / "task_specs.jsonl"
    manifest_path = root / "task-specs.manifest.json"
    tasks = read_jsonl(tasks_path)
    manifest = read_json(manifest_path)
    manifest_schema = str(manifest.get("schema_version", ""))
    benchmark_prompt_overlap = manifest.get(
        "benchmark_prompt_overlap",
        manifest.get("exact_public_benchmark_overlap"),
    )
    sealed_task_files_read = manifest.get(
        "sealed_task_files_read",
        manifest.get("sealed_or_fresh_external_holdouts_opened"),
    )
    public_task_has_verifier = manifest.get("public_task_has_verifier")
    if public_task_has_verifier is None and manifest_schema == "studyhub.codex-hermes-training-tasks.v2":
        public_task_has_verifier = any(
            bool(FORBIDDEN_PUBLIC_FIELDS & task.keys()) for task in tasks
        )
    errors: list[dict[str, Any]] = []
    families: Counter[str] = Counter()
    source_groups: Counter[str] = Counter()
    tool_routes: Counter[str] = Counter()
    schemas: Counter[str] = Counter()
    task_ids: set[str] = set()
    total_documents = 0
    total_routes = 0
    executable_routes = 0

    if sha256(tasks_path) != manifest.get("task_specs_sha256"):
        _record(errors, "<manifest>", "task_specs_hash_mismatch")
    if benchmark_prompt_overlap != 0:
        _record(errors, "<manifest>", "benchmark_prompt_overlap")
    if sealed_task_files_read is not False:
        _record(errors, "<manifest>", "sealed_files_not_proven_unread")
    if public_task_has_verifier is not False:
        _record(errors, "<manifest>", "public_verifier_exposure")

    for task in tasks:
        task_id = str(task.get("task_id", ""))
        if not task_id:
            _record(errors, "<missing>", "task_id_missing")
            continue
        if task_id in task_ids:
            _record(errors, task_id, "duplicate_task_id")
            continue
        task_ids.add(task_id)
        families[str(task.get("family", "unknown"))] += 1
        schemas[str(task.get("schema_version", "unknown"))] += 1
        exposed = sorted(FORBIDDEN_PUBLIC_FIELDS & task.keys())
        if exposed:
            _record(errors, task_id, "hidden_fields_exposed", fields=exposed)
        metadata = task.get("metadata", {})
        if metadata.get("benchmark_overlap") is not False:
            _record(errors, task_id, "task_benchmark_overlap")
        task_source_groups = set(map(str, metadata.get("source_group_ids", [])))
        if not task_source_groups or str(metadata.get("source_group_id", "")) not in task_source_groups:
            _record(errors, task_id, "source_group_provenance_invalid")
        source_groups.update(task_source_groups)

        paths = {
            "environment": root / "environments" / f"{task_id}.json",
            "fixture": root / "fixtures" / f"{task_id}.json",
            "verifier": root / "verifiers" / f"{task_id}.json",
        }
        missing = sorted(name for name, path in paths.items() if not path.is_file())
        if missing:
            _record(errors, task_id, "hidden_assets_missing", assets=missing)
            continue
        environment = read_json(paths["environment"])
        fixture = read_json(paths["fixture"])
        verifier = read_json(paths["verifier"])
        tools = {str(row.get("name", "")): row for row in environment.get("tools", [])}
        allowed_tools = set(map(str, task.get("allowed_tools", [])))
        if allowed_tools != set(tools):
            _record(errors, task_id, "allowed_tool_mismatch")

        documents = environment.get("documents", [])
        total_documents += len(documents)
        empty_documents = [str(row.get("source_id", "")) for row in documents if not str(row.get("text", "")).strip()]
        if empty_documents:
            _record(errors, task_id, "empty_documents", source_ids=sorted(empty_documents))
        document_ids = {str(row.get("source_id", "")) for row in documents if str(row.get("text", "")).strip()}

        routes = fixture.get("routes", [])
        total_routes += len(routes)
        routes_by_name: Counter[str] = Counter(str(route.get("name", "")) for route in routes)
        tool_routes.update(routes_by_name)
        for route in routes:
            name = str(route.get("name", ""))
            if name not in tools:
                _record(errors, task_id, "route_tool_missing", tool=name)
                continue
            result = _execute_route(environment, fixture, route)
            if any(
                code in {"fixture_route_not_found", "source_not_discovered", "source_not_found", "unknown_tool"}
                for code in result["errors"]
            ):
                _record(errors, task_id, "route_not_executable", tool=name, runtime_errors=result["errors"])
            else:
                executable_routes += 1

        expected_tools = list(map(str, verifier.get("expected_tool_names", [])))
        for name in expected_tools:
            capability = str(tools.get(name, {}).get("capability", ""))
            reachable = bool(routes_by_name[name])
            if capability == "knowledge_search":
                # An empty local corpus is a valid, executable fallback precondition.
                reachable = name in tools
            elif capability == "knowledge_read":
                reachable = bool(document_ids or routes_by_name[name])
            if not reachable:
                _record(errors, task_id, "expected_tool_unreachable", tool=name, capability=capability)

        route_results = [route.get("result") for route in routes]
        reachable_markers: set[str] = set()
        for result in route_results:
            reachable_markers.update(nested_values(result, "error"))
            reachable_markers.update(nested_values(result, "postcondition"))
        required_markers = set(map(str, verifier.get("required_observation_markers", [])))
        missing_markers = sorted(required_markers - reachable_markers)
        if missing_markers:
            _record(errors, task_id, "required_markers_unreachable", markers=missing_markers)

        reachable_evidence = set(document_ids)
        for result in route_results:
            reachable_evidence.update(evidence_source_ids(result))
        allowed_citations = set(map(str, verifier.get("allowed_citations", [])))
        unreachable_citations = sorted(allowed_citations - reachable_evidence)
        if unreachable_citations:
            _record(errors, task_id, "allowed_citations_unreachable", source_ids=unreachable_citations)

        family = str(task.get("family", ""))
        if family == "recovery_acl" and "permission_denied" not in reachable_markers:
            _record(errors, task_id, "acl_permission_route_missing")
        if family == "web_fallback_conflict":
            search_urls = {
                str(result.get("url", ""))
                for route in routes
                if route.get("name") == "web_search" and isinstance(route.get("result"), dict)
                for result in route["result"].get("results", [])
                if isinstance(result, dict) and result.get("url")
            }
            fetch_urls = {
                str(route.get("arguments", {}).get("url", "")) for route in routes if route.get("name") == "web_fetch"
            }
            missing_fetch_urls = sorted(search_urls - fetch_urls)
            if missing_fetch_urls:
                _record(errors, task_id, "web_search_results_not_fetchable", urls=missing_fetch_urls)
            if "web_fetch" in expected_tools and not routes_by_name["web_fetch"]:
                _record(errors, task_id, "web_fetch_route_missing")

    if len(tasks) != manifest.get("tasks"):
        _record(errors, "<manifest>", "task_count_mismatch", observed=len(tasks), expected=manifest.get("tasks"))
    if dict(sorted(families.items())) != manifest.get("family_counts"):
        _record(errors, "<manifest>", "family_count_mismatch")
    maximum_group_rows = max(source_groups.values(), default=0)
    group_cap_value = manifest.get("max_rows_per_source_group_contract")
    if group_cap_value is None and manifest_schema == "studyhub.codex-hermes-training-tasks.v2":
        group_cap_value = 1
    group_cap = int(group_cap_value or 0)
    if maximum_group_rows > group_cap:
        _record(
            errors,
            "<manifest>",
            "source_group_cap_exceeded",
            observed=maximum_group_rows,
            maximum=group_cap,
        )

    report = {
        "schema_version": "studyhub.teacher-task-contract-audit.v1",
        "status": "PASS" if not errors else "FAIL",
        "root": str(root),
        "tasks": len(tasks),
        "unique_task_ids": len(task_ids),
        "families": dict(sorted(families.items())),
        "unique_source_groups": len(source_groups),
        "rows_per_source_group": {
            "max": maximum_group_rows,
            "groups_over_10": sum(value > 10 for value in source_groups.values()),
        },
        "task_schemas": dict(sorted(schemas.items())),
        "documents": total_documents,
        "fixture_routes": total_routes,
        "executable_routes": executable_routes,
        "tool_routes": dict(sorted(tool_routes.items())),
        "benchmark_prompt_overlap": benchmark_prompt_overlap,
        "sealed_task_files_read": sealed_task_files_read,
        "task_specs_sha256": sha256(tasks_path),
        "errors": errors,
        "error_count": len(errors),
    }
    output = root / "task-contract-audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / "datasets/interim/studyhub_teacher_v2_3")
    return parser.parse_args()


def main() -> int:
    report = audit_root(parse_args().root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
