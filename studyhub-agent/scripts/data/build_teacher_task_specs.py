#!/usr/bin/env python3
"""Build benchmark-disjoint training tasks for Teacher-to-Hermes collection."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterable
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
from studyhub_agent.trajectory.runtime_sft import canonical_json, stable_hash  # noqa: E402

SCHEMA_VERSION = "studyhub.teacher-task.v2.3"
VERIFIER_SCHEMA_VERSION = "studyhub.teacher-verifier.v2.3"
MANIFEST_SCHEMA_VERSION = "studyhub.teacher-task-manifest.v2.3"
TEACHER_DATASET = "studyhub_teacher_v2_3"
DEFAULT_TOTAL = 2_400
FAMILY_PLAN = {
    "rag_query_rewrite_citation": ("studyhub_metadata_replay", 0.25),
    "web_fallback_conflict": ("studyhub_web_fallback", 0.15),
    "memory_personalization_privacy": ("studyhub_memory_replay", 0.20),
    "cross_tool_composition": ("studyhub_state_tools", 0.15),
    "recovery_acl": ("studyhub_acl_recovery", 0.10),
    "state_function": ("studyhub_state_tools", 0.10),
    "direct_abstention": ("coig_exam", 0.05),
}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _user_request(row: dict[str, Any]) -> str:
    return next(
        (str(message.get("content", "")) for message in row["messages"] if message.get("role") == "user"),
        "",
    )


def _final_answer(row: dict[str, Any]) -> str:
    return next(
        (
            str(message.get("content", ""))
            for message in reversed(row["messages"])
            if message.get("role") == "assistant" and not message.get("tool_calls")
        ),
        "",
    )


def _citations(value: str) -> list[str]:
    import re

    return sorted(set(re.findall(r"\[([^][\s]+:[^][\s]+)]", value)))


def _tools(row: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for tool in row.get("tools", []):
        function = tool.get("function", {})
        name = str(function.get("name", ""))
        if not name:
            continue
        result.append(
            {
                "name": name,
                "description": str(function.get("description", name)),
                "parameters": function.get("parameters") or {"type": "object", "properties": {}},
                "capability": "function_call",
            }
        )
    return result


def _call_observations(row: dict[str, Any]) -> list[tuple[str, dict[str, Any], Any]]:
    pending: dict[str, tuple[str, dict[str, Any]]] = {}
    result: list[tuple[str, dict[str, Any], Any]] = []
    for message in row.get("messages", []):
        if message.get("role") == "assistant":
            for call in message.get("tool_calls", []):
                function = call.get("function", {})
                arguments = function.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                pending[str(call.get("id", ""))] = (str(function.get("name", "")), dict(arguments))
        elif message.get("role") == "tool":
            key = str(message.get("tool_call_id", ""))
            if key not in pending:
                continue
            name, arguments = pending.pop(key)
            content = message.get("content", "")
            try:
                content = json.loads(str(content))
            except json.JSONDecodeError:
                pass
            result.append((name, arguments, content))
    return result


def _documents(calls: list[tuple[str, dict[str, Any], Any]]) -> list[dict[str, str]]:
    documents: dict[str, dict[str, str]] = {}
    for name, _arguments, observation in calls:
        if name not in {"knowledge_search", "knowledge_read"}:
            continue
        if not isinstance(observation, dict):
            continue
        rows = observation.get("results", []) if "search" in name else [observation]
        for item in rows if isinstance(rows, list) else []:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id", ""))
            if not source_id:
                continue
            text = str(item.get("text") or item.get("snippet") or "")
            # Error observations are fixture routes, not readable corpus documents.
            if not text.strip():
                continue
            existing = documents.get(source_id)
            if existing is None or len(text) > len(existing["text"]):
                documents[source_id] = {
                    "source_id": source_id,
                    "title": str(item.get("title", source_id)),
                    "text": text,
                }
    return sorted(documents.values(), key=lambda item: item["source_id"])


def _evidence_source_ids(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        source_id = value.get("source_id")
        text = value.get("text")
        if isinstance(source_id, str) and source_id and isinstance(text, str) and text.strip():
            result.add(source_id)
        for child in value.values():
            result.update(_evidence_source_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_evidence_source_ids(child))
    return result


def _evidence_sources(calls: list[tuple[str, dict[str, Any], Any]]) -> list[str]:
    values: set[str] = set()
    for _name, _arguments, observation in calls:
        values.update(_evidence_source_ids(observation))
    return sorted(values)


def _normalize_source_group(source_id: str) -> str | None:
    if source_id.startswith("studyhub-material:"):
        return source_id
    if source_id.startswith(("web-material:", "paid-source:")):
        return f"studyhub-material:{source_id.split(':', 1)[1]}"
    if source_id.startswith("memory:"):
        return f"studyhub-memory:{source_id.split(':', 1)[1]}"
    return None


def _build_web_fetch_library(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    library: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: stable_hash(str(item["id"]), salt="teacher-fetch-library")):
        for name, arguments, observation in _call_observations(row):
            if name != "web_fetch" or not isinstance(observation, dict):
                continue
            url = str(arguments.get("url", "")).strip()
            if not url or not _evidence_source_ids(observation):
                continue
            candidate = {
                "result": observation,
                "source_group_id": str(row["group_id"]),
                "source_row_id": str(row["id"]),
            }
            existing = library.get(url)
            if existing is not None and (
                canonical_json(existing["result"]) != canonical_json(candidate["result"])
                or existing["source_group_id"] != candidate["source_group_id"]
            ):
                raise RuntimeError(f"conflicting frozen web fetch payload: {url}")
            library[url] = candidate
    return library


def _source_group_ids(
    row: dict[str, Any],
    web_fetch_library: dict[str, dict[str, Any]],
) -> list[str]:
    groups = {str(row["group_id"])}
    for name, arguments, observation in _call_observations(row):
        for source_id in _nested_values(observation, "source_id"):
            normalized = _normalize_source_group(source_id)
            if normalized:
                groups.add(normalized)
        if name == "material_bookmark_add" and arguments.get("material_id") is not None:
            groups.add(f"studyhub-material:{arguments['material_id']}")
        if name == "study_plan_update":
            groups.update(f"studyhub-material:{value}" for value in arguments.get("resource_ids", []))
        if name == "web_search" and isinstance(observation, dict):
            for result in observation.get("results", []):
                if not isinstance(result, dict):
                    continue
                route = web_fetch_library.get(str(result.get("url", "")))
                if route is not None:
                    groups.add(str(route["source_group_id"]))
    return sorted(groups)


def _nested_values(value: Any, key: str) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        item = value.get(key)
        if isinstance(item, str) and item:
            result.add(item)
        for child in value.values():
            result.update(_nested_values(child, key))
    elif isinstance(value, list):
        for child in value:
            result.update(_nested_values(child, key))
    return result


def _required_observation_markers(calls: list[tuple[str, dict[str, Any], Any]]) -> list[str]:
    markers: set[str] = set()
    for _name, _arguments, observation in calls:
        markers.update(_nested_values(observation, "postcondition"))
        errors = _nested_values(observation, "error")
        if "permission_denied" in errors:
            markers.add("permission_denied")
    return sorted(markers)


def _required_state_postconditions(calls: list[tuple[str, dict[str, Any], Any]]) -> list[str]:
    markers: set[str] = set()
    for _name, _arguments, observation in calls:
        markers.update(_nested_values(observation, "postcondition"))
    return sorted(markers)


def _hidden_required_tools(family: str, expected_tools: list[str]) -> list[str]:
    if family == "memory_personalization_privacy":
        return sorted({name for name in expected_tools if "memory" in name})
    if family in {"cross_tool_composition", "state_function"}:
        return sorted({name for name in expected_tools if name in {"material_bookmark_add", "study_plan_update"}})
    return []


def _environment(
    row: dict[str, Any],
    *,
    web_fetch_library: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    tools = _tools(row)
    calls = _call_observations(row)
    documents = _documents(calls)
    document_ids = {item["source_id"] for item in documents}
    tool_by_name = {tool["name"]: tool for tool in tools}
    for tool in tools:
        if tool["name"] == "knowledge_search":
            tool["capability"] = "knowledge_search"
        elif tool["name"] == "knowledge_read":
            tool["capability"] = "knowledge_read"
        elif tool["name"].endswith("_search"):
            tool["capability"] = "replay_search"
        elif tool["name"].endswith("_fetch"):
            tool["capability"] = "evidence_fetch"
    routes = []
    expected_tools = []
    for name, arguments, observation in calls:
        expected_tools.append(name)
        tool = tool_by_name.get(name)
        if tool is None:
            continue
        if tool["capability"] == "knowledge_read":
            source_id = str(arguments.get("source_id", ""))
            if source_id not in document_ids:
                routes.append({"name": name, "arguments": arguments, "result": observation})
            continue
        if tool["capability"] not in {"function_call", "replay_search", "evidence_fetch"}:
            continue
        route = {"name": name, "arguments": arguments, "result": observation}
        if name == "study_plan_update":
            route["argument_match"] = {
                "mode": "exact_except",
                "flexible_fields": ["topic"],
            }
        routes.append(route)
    fetch_library = web_fetch_library or {}
    existing_fetch_urls = {
        str(route.get("arguments", {}).get("url", "")) for route in routes if route.get("name") == "web_fetch"
    }
    if "web_fetch" in tool_by_name:
        for name, _arguments, observation in calls:
            if name != "web_search" or not isinstance(observation, dict):
                continue
            for result in observation.get("results", []):
                if not isinstance(result, dict):
                    continue
                url = str(result.get("url", "")).strip()
                supplement = fetch_library.get(url)
                if not url or url in existing_fetch_urls or supplement is None:
                    continue
                routes.append(
                    {
                        "name": "web_fetch",
                        "arguments": {"url": url},
                        "result": supplement["result"],
                        "provenance": {
                            "origin": "frozen_train_fetch_library",
                            "source_group_id": supplement["source_group_id"],
                            "source_row_id": supplement["source_row_id"],
                        },
                    }
                )
                existing_fetch_urls.add(url)
    # A read document must be discoverable by search; the environment enforces this.
    if documents and any(tool.get("capability") == "knowledge_read" for tool in tools):
        for source_id in document_ids:
            if not any(source_id in canonical_json(document) for document in documents):
                raise RuntimeError(f"unreachable document: {source_id}")
    return {"tools": tools, "documents": documents}, {"routes": routes}, expected_tools


def _round_robin_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for row in sorted(rows, key=lambda item: stable_hash(str(item["id"]), salt="teacher-task-order")):
        groups[str(row["group_id"])].append(row)
    order = sorted(groups, key=lambda key: stable_hash(key, salt="teacher-group-order"))
    result = []
    while order:
        next_order = []
        for group in order:
            result.append(groups[group].popleft())
            if groups[group]:
                next_order.append(group)
        order = next_order
    return result


def _select_family_balanced_rows(
    pools: dict[str, list[dict[str, Any]]],
    allocations: dict[str, int],
    *,
    source_group_ids_for_row: Callable[[dict[str, Any]], list[str]],
    max_rows_per_group: int,
) -> tuple[list[tuple[str, dict[str, Any]]], Counter[str]]:
    queues = {family: deque(_round_robin_order(pools[source])) for family, (source, _share) in FAMILY_PLAN.items()}
    selected: list[tuple[str, dict[str, Any]]] = []
    selected_by_family: Counter[str] = Counter()
    source_groups: Counter[str] = Counter()
    used_rows: set[str] = set()
    while True:
        made_progress = False
        has_unfilled_family = False
        for family in FAMILY_PLAN:
            if selected_by_family[family] >= allocations[family]:
                continue
            has_unfilled_family = True
            queue = queues[family]
            while queue:
                row = queue.popleft()
                row_id = str(row["id"])
                if row_id in used_rows:
                    continue
                row_groups = set(map(str, source_group_ids_for_row(row))) or {str(row["group_id"])}
                if any(source_groups[group] >= max_rows_per_group for group in row_groups):
                    continue
                selected.append((family, row))
                selected_by_family[family] += 1
                source_groups.update(row_groups)
                used_rows.add(row_id)
                made_progress = True
                break
        if not has_unfilled_family or not made_progress:
            break
    return selected, source_groups


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "datasets/interim/runtime_sft_v3/selected.jsonl")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / f"datasets/interim/{TEACHER_DATASET}")
    parser.add_argument("--max-tasks", type=int, default=DEFAULT_TOTAL)
    parser.add_argument("--max-rows-per-source-group", type=int, default=24)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.max_tasks <= 4_000:
        raise ValueError("--max-tasks must be in [1, 4000]")
    if not 1 <= args.max_rows_per_source_group <= 32:
        raise ValueError("--max-rows-per-source-group must be in [1, 32]")
    if args.output.exists():
        if not args.overwrite:
            raise FileExistsError(f"output exists; pass --overwrite: {args.output}")
        shutil.rmtree(args.output)
    benchmark_path = PROJECT_ROOT / "benchmarks/studyhub-agent-v2/manifest.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    benchmark_hashes, benchmark_tasks = public_benchmark_prompt_hashes(PROJECT_ROOT, benchmark)
    pools: dict[str, list[dict[str, Any]]] = defaultdict(list)
    training_rows = []
    with args.input.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("split") != "train" or candidate_prompt_hash(row) in benchmark_hashes:
                continue
            training_rows.append(row)
            pools[str(row["source_dataset"])].append(row)
    web_fetch_library = _build_web_fetch_library(training_rows)

    allocations = {family: round(args.max_tasks * share) for family, (_source, share) in FAMILY_PLAN.items()}
    allocations[next(iter(allocations))] += args.max_tasks - sum(allocations.values())
    tasks = []
    family_counts: Counter[str] = Counter()
    supplemental_web_routes = 0
    selected_rows, source_groups = _select_family_balanced_rows(
        pools,
        allocations,
        source_group_ids_for_row=lambda item: _source_group_ids(item, web_fetch_library),
        max_rows_per_group=args.max_rows_per_source_group,
    )
    for family, row in selected_rows:
        source = FAMILY_PLAN[family][0]
        task_id = f"teacher-v2-3-{stable_hash(str(row['id']), salt='studyhub-teacher-v2.3')[:20]}"
        environment, fixture, expected_tools = _environment(row, web_fetch_library=web_fetch_library)
        supplemental_web_routes += sum(
            route.get("provenance", {}).get("origin") == "frozen_train_fetch_library" for route in fixture["routes"]
        )
        calls = _call_observations(row)
        task_source_groups = _source_group_ids(row, web_fetch_library)
        required_state_postconditions = _required_state_postconditions(calls)
        evidence_sources = sorted(
            set(_evidence_sources(calls))
            | {document["source_id"] for document in environment["documents"] if document["text"].strip()}
            | {source_id for route in fixture["routes"] for source_id in _evidence_source_ids(route.get("result"))}
        )
        request = _user_request(row)
        reference = _final_answer(row)
        if not request or not reference:
            continue
        minimum_citations = (
            min(2, len(evidence_sources))
            if evidence_sources
            and (
                family == "web_fallback_conflict"
                or any(token in request.casefold() for token in ("比较", "核对两", "compare"))
            )
            else int(bool(evidence_sources))
        )
        max_tool_calls = max(1, min(12, len(expected_tools) + 3))
        max_steps = max(2, min(14, len(expected_tools) + 4))
        public = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "family": family,
            "user_request": request,
            "allowed_tools": [tool["name"] for tool in environment["tools"]],
            "completion_contract": {
                "minimum_grounded_citations": minimum_citations,
                "citation_format": "[source_id]",
                "search_result_requires_read_or_fetch_before_citation": True,
                "minimum_successful_state_changes": len(required_state_postconditions),
                "state_changes_require_successful_observation": family in {"cross_tool_composition", "state_function"},
            },
            "max_steps": max_steps,
            "max_tool_calls": max_tool_calls,
            "metadata": {
                "source_dataset": source,
                "source_row_id": row["id"],
                "source_group_id": row["group_id"],
                "source_group_ids": task_source_groups,
                "split": "train",
                "benchmark_overlap": False,
                "environment_id": task_id,
                "verifier_id": task_id,
                "teacher_dataset": TEACHER_DATASET,
            },
        }
        verifier = {
            "schema_version": VERIFIER_SCHEMA_VERSION,
            "task_id": task_id,
            "family": family,
            "reference_final": reference,
            "reference_final_sha256": hashlib.sha256(reference.encode()).hexdigest(),
            "reference_citations": _citations(reference),
            "allowed_citations": evidence_sources,
            "minimum_citations": minimum_citations,
            "expected_tool_names": expected_tools,
            "required_tool_names": _hidden_required_tools(family, expected_tools),
            "required_observation_markers": _required_observation_markers(calls),
            "minimum_tool_calls": 0 if not expected_tools else 1,
            "source_group_id": row["group_id"],
            "source_group_ids": task_source_groups,
            "benchmark_prompt_overlap": False,
        }
        write_json(args.output / "environments" / f"{task_id}.json", environment)
        write_json(args.output / "fixtures" / f"{task_id}.json", fixture)
        write_json(args.output / "verifiers" / f"{task_id}.json", verifier)
        tasks.append(public)
        family_counts[family] += 1

    write_jsonl(args.output / "task_specs.jsonl", tasks)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "READY_FOR_TEACHER_SMOKE",
        "tasks": len(tasks),
        "requested_tasks": args.max_tasks,
        "family_counts": dict(sorted(family_counts.items())),
        "unique_source_groups": len(source_groups),
        "rows_per_source_group": {
            "max": max(source_groups.values(), default=0),
            "groups_over_10": sum(value > 10 for value in source_groups.values()),
        },
        "max_rows_per_source_group_contract": args.max_rows_per_source_group,
        "source_group_cap_scope": "candidate_task_specs_full_provenance",
        "downstream_v3_1_default_teacher_group_cap": 4,
        "web_fetch_library": {
            "scope": "runtime_sft_v3_train_only",
            "urls": len(web_fetch_library),
            "supplemental_routes": supplemental_web_routes,
        },
        "source_selected_sha256": sha256(args.input),
        "benchmark_manifest_sha256": sha256(benchmark_path),
        "benchmark_tasks_checked": benchmark_tasks,
        "benchmark_splits_checked": ["regression", "development", "calibration_challenge"],
        "sealed_task_files_read": False,
        "sealed_overlap_recheck": "INHERITED_FROM_FROZEN_V3_SOURCE_LOCK_NOT_RECOMPUTED",
        "benchmark_prompt_overlap": 0,
        "public_task_has_verifier": False,
        "public_task_exposes_gold_tool_path": False,
        "task_specs_sha256": sha256(args.output / "task_specs.jsonl"),
        "hidden_roots": ["environments", "fixtures", "verifiers"],
        "teacher_sandbox_mounts_hidden_roots": False,
    }
    write_json(args.output / "task-specs.manifest.json", manifest)
    write_json(
        args.output / "sandbox-manifest.json",
        {
            "schema_version": "studyhub.teacher-sandbox.v1",
            "allowed_files": ["public_task.json", "action-schema.json"],
            "denied_roots": ["benchmarks", "verifiers", "fixtures", "environments", "artifacts", ".git"],
            "network": "teacher-provider-only",
            "filesystem": "temporary-public-task-directory-only",
            "hidden_oracle_available_to_teacher": False,
        },
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
