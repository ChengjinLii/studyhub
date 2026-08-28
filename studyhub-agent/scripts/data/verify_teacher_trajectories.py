#!/usr/bin/env python3
"""Verify raw Teacher-to-Hermes runs and emit accepted/rejected datasets."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for entry in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from scripts.data.select_runtime_sft_v3 import sha256  # noqa: E402
from studyhub_agent.trajectory.runtime_sft import (  # noqa: E402
    trajectory_fingerprint,
    validate_runtime_trajectory,
)

CITATION = re.compile(r"\[([^][\s]+:[^][\s]+)]")


def terms(value: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]", value.casefold()))


def semantic_overlap(reference: str, candidate: str) -> float:
    expected = terms(reference)
    actual = terms(candidate)
    return len(expected & actual) / max(len(expected), 1)


def _nested_strings(value: Any, key: str) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        item = value.get(key)
        if isinstance(item, str) and item:
            result.add(item)
        for child in value.values():
            result.update(_nested_strings(child, key))
    elif isinstance(value, list):
        for child in value:
            result.update(_nested_strings(child, key))
    return result


def _evidence_tool(name: str) -> bool:
    return name == "knowledge_read" or name.endswith("_read") or name.endswith("_fetch")


def observed_citations(run: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for message in run.get("messages", []):
        if message.get("role") != "tool":
            continue
        if not _evidence_tool(str(message.get("name", ""))):
            continue
        content = str(message.get("content", ""))
        values.update(CITATION.findall(content))
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue
        values.update(_nested_strings(payload, "source_id"))
        for citation in _nested_strings(payload, "citation"):
            values.update(CITATION.findall(citation))
    return values


def observed_markers(run: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for message in run.get("messages", []):
        if message.get("role") != "tool":
            continue
        try:
            payload = json.loads(str(message.get("content", "")))
        except json.JSONDecodeError:
            continue
        result.update(_nested_strings(payload, "postcondition"))
        result.update(_nested_strings(payload, "error"))
    return result


def verify_run(run: dict[str, Any], task: dict[str, Any], verifier: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    if run.get("status") != "COMPLETED":
        failures.append("run_not_completed")
    controller = run.get("controller", {})
    if controller.get("hermes_registry_dispatch") is not True:
        failures.append("not_dispatched_by_hermes")
    if controller.get("controller_errors"):
        failures.append("controller_errors")
    if controller.get("environment_errors"):
        failures.append("environment_errors")
    if controller.get("runtime_errors"):
        failures.append("runtime_errors")
    if int(controller.get("invalid_tool_calls", 0)):
        failures.append("invalid_tool_calls")
    if int(controller.get("tool_calls", 0)) > int(task["max_tool_calls"]):
        failures.append("tool_budget_exceeded")
    provider_errors = sorted(
        {
            str(event["error_code"])
            for event in run.get("provider_events", [])
            if isinstance(event, dict) and event.get("error_code")
        }
    )
    failures.extend(f"provider:{code}" for code in provider_errors)
    final = str(run.get("final_answer", "")).strip()
    if not final:
        failures.append("empty_final")

    expected_tools = set(verifier.get("expected_tool_names", []))
    required_tools = set(verifier.get("required_tool_names", []))
    actual_tools = {
        str(call.get("function", {}).get("name", ""))
        for message in run.get("messages", [])
        for call in message.get("tool_calls", [])
    }
    if int(verifier.get("minimum_tool_calls", 0)) and not (expected_tools & actual_tools):
        failures.append("required_tool_family_missing")
    if not required_tools.issubset(actual_tools):
        failures.append("required_tool_sequence_missing")
    required_markers = set(verifier.get("required_observation_markers", []))
    actual_markers = observed_markers(run)
    if not required_markers.issubset(actual_markers):
        failures.append("required_observation_marker_missing")

    answer_citations = set(CITATION.findall(final))
    observed = observed_citations(run) | set(controller.get("read_source_ids", []))
    invalid_citations = sorted(answer_citations - observed)
    if invalid_citations:
        failures.append("citation_not_observed")
    allowed_citations = set(verifier.get("allowed_citations", []))
    disallowed_citations = sorted(answer_citations - allowed_citations) if allowed_citations else []
    if disallowed_citations:
        failures.append("citation_not_allowed")
    grounded_citations = answer_citations & observed
    minimum_citations = int(verifier.get("minimum_citations", 0))
    if len(grounded_citations) < minimum_citations:
        failures.append("insufficient_grounded_citations")
    required_citations = set(verifier.get("required_citations", []))
    if not required_citations.issubset(grounded_citations):
        failures.append("required_citation_missing")
    overlap = semantic_overlap(str(verifier.get("reference_final", "")), final)
    minimum_overlap = 0.20 if task.get("family") == "direct_abstention" else 0.25
    if overlap < minimum_overlap:
        failures.append("insufficient_answer_support_overlap")
    if verifier.get("benchmark_prompt_overlap") is not False:
        failures.append("verifier_benchmark_overlap")

    diagnostics = {
        "semantic_overlap": round(overlap, 6),
        "minimum_semantic_overlap": minimum_overlap,
        "actual_tools": sorted(actual_tools),
        "expected_tool_names": sorted(expected_tools),
        "required_tool_names": sorted(required_tools),
        "actual_tool_sequence": [
            str(call.get("function", {}).get("name", ""))
            for message in run.get("messages", [])
            for call in message.get("tool_calls", [])
        ],
        "answer_citations": sorted(answer_citations),
        "observed_citations": sorted(observed),
        "invalid_citations": invalid_citations,
        "allowed_citations": sorted(allowed_citations),
        "disallowed_citations": disallowed_citations,
        "grounded_citations": sorted(grounded_citations),
        "minimum_citations": minimum_citations,
        "provider_errors": provider_errors,
        "required_observation_markers": sorted(required_markers),
        "observed_markers": sorted(actual_markers),
    }
    return sorted(set(failures)), diagnostics


def accepted_record(
    run: dict[str, Any],
    task: dict[str, Any],
    verifier: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    provider = run.get("provider", {})
    interface = str(provider.get("interface", "unknown"))
    repaired = bool(
        run.get("collection_mode") == "dagger_repair" or run.get("controller", {}).get("policy_corrections")
    )
    tier = "teacher_repaired_complete" if repaired else "teacher_verified_complete"
    messages = run["messages"]
    runtime_native = bool(
        any(message.get("role") == "assistant" and message.get("tool_calls") for message in messages)
        and any(message.get("role") == "tool" for message in messages)
        and messages[-1].get("role") == "assistant"
        and str(messages[-1].get("content", "")).strip()
    )
    teacher_dataset = str(task.get("metadata", {}).get("teacher_dataset", "studyhub_teacher_v1"))
    record_id = (
        f"teacher-v1:{run['run_id']}"
        if teacher_dataset == "studyhub_teacher_v1"
        else f"{teacher_dataset}:{run['run_id']}"
    )
    record: dict[str, Any] = {
        "schema_version": "studyhub.runtime-sft-trajectory.v3",
        "id": record_id,
        "source_dataset": teacher_dataset,
        "source_id": run["run_id"],
        "group_id": task["metadata"]["source_group_id"],
        "split": "train",
        "task_family": task["family"],
        "capability_tags": [task["family"], "teacher_policy", "hermes_runtime"],
        "quality_tier": tier,
        "trajectory_status": "complete",
        "runtime_native": runtime_native,
        "tools": run["tools"],
        "messages": messages,
        "teacher": {
            "interface": interface,
            "model": provider.get("model"),
            "candidate_index": run.get("candidate_index"),
            "path_signature": run.get("path_signature"),
            "controller": "pinned_hermes_registry_dispatch",
            "hermes_commit": run.get("controller", {}).get("hermes_commit"),
            "policy_corrections": len(run.get("controller", {}).get("policy_corrections", [])),
        },
        "verification": diagnostics,
        "provenance": {
            "revision": run.get("collector_git_commit", "unknown"),
            "license": "StudyHub-internal-derived",
            "source_url": f"local://{teacher_dataset}",
            "raw_files": [run.get("raw_run_path", "raw_runs")],
        },
    }
    record["content_sha256"] = trajectory_fingerprint(record)
    contract = validate_runtime_trajectory(record)
    if contract:
        raise RuntimeError(f"accepted teacher trajectory violates runtime contract: {contract}")
    return record


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_tasks(root: Path) -> dict[str, dict[str, Any]]:
    return {
        row["task_id"]: row
        for row in (
            json.loads(line)
            for line in (root / "task_specs.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def verify_root(root: Path) -> dict[str, Any]:
    tasks = load_tasks(root)
    accepted = []
    rejected = []
    failure_taxonomy: Counter[str] = Counter()
    path_signatures: Counter[str] = Counter()
    providers: Counter[str] = Counter()
    capabilities: Counter[str] = Counter()
    source_groups: Counter[str] = Counter()
    task_schema_versions: Counter[str] = Counter()
    provider_errors: Counter[str] = Counter()
    quality_tiers: Counter[str] = Counter()
    collection_modes: Counter[str] = Counter()
    policy_correction_events = 0
    runs_with_policy_corrections = 0
    turn_counts: list[int] = []
    tool_call_counts: list[int] = []
    latencies: list[float] = []
    usage_totals: defaultdict[str, int] = defaultdict(int)
    for path in sorted((root / "raw_runs").glob("*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        collection_modes[str(run.get("collection_mode", "unknown"))] += 1
        corrections = run.get("controller", {}).get("policy_corrections", [])
        if isinstance(corrections, list) and corrections:
            runs_with_policy_corrections += 1
            policy_correction_events += len(corrections)
        task_id = str(run.get("task_id", ""))
        task = tasks.get(task_id)
        if task is not None:
            task_schema_versions[str(task.get("schema_version", "unknown"))] += 1
        verifier_path = root / "verifiers" / f"{task_id}.json"
        if task is None or not verifier_path.is_file():
            failures, diagnostics = ["task_or_verifier_missing"], {}
        else:
            verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
            failures, diagnostics = verify_run(run, task, verifier)
        for code in diagnostics.get("provider_errors", []):
            provider_errors[code] += 1
        events = [event for event in run.get("provider_events", []) if isinstance(event, dict)]
        latencies.append(sum(float(event.get("duration_seconds", 0.0)) for event in events))
        for event in events:
            usage = event.get("usage", {})
            if not isinstance(usage, dict):
                continue
            aliases = {
                "input_tokens": ("input_tokens", "prompt_tokens"),
                "output_tokens": ("output_tokens", "completion_tokens"),
                "total_tokens": ("total_tokens",),
                "reasoning_tokens": ("reasoning_tokens",),
            }
            for key, candidates in aliases.items():
                try:
                    value = next((usage[candidate] for candidate in candidates if usage.get(candidate) is not None), 0)
                    usage_totals[key] += int(value)
                except (TypeError, ValueError):
                    continue
        turn_counts.append(sum(message.get("role") == "assistant" for message in run.get("messages", [])))
        tool_call_counts.append(int(run.get("controller", {}).get("tool_calls", 0)))
        if failures:
            failure_taxonomy.update(failures)
            rejected.append(
                {
                    "schema_version": "studyhub.teacher-rejection.v1",
                    "run_id": run.get("run_id"),
                    "task_id": task_id,
                    "family": run.get("family"),
                    "provider": run.get("provider"),
                    "failures": failures,
                    "diagnostics": diagnostics,
                    "raw_run_sha256": sha256(path),
                }
            )
            continue
        verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
        record = accepted_record(run, task, verifier, diagnostics)
        accepted.append(record)
        quality_tiers[str(record.get("quality_tier", "unknown"))] += 1
        path_signatures[str(run.get("path_signature", ""))] += 1
        providers[str(run.get("provider", {}).get("interface", "unknown"))] += 1
        capabilities[str(task.get("family", "unknown"))] += 1
        source_groups[str(task.get("metadata", {}).get("source_group_id", "unknown"))] += 1

    write_jsonl(root / "accepted.jsonl", accepted)
    write_jsonl(root / "rejected.jsonl", rejected)
    write_jsonl(
        root / "failure_taxonomy.jsonl",
        [{"failure": key, "count": value} for key, value in failure_taxonomy.most_common()],
    )
    manifest = {
        "schema_version": "studyhub.teacher-verification-manifest.v1",
        "status": "PASS",
        "raw_runs": len(accepted) + len(rejected),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "acceptance_rate": round(len(accepted) / max(len(accepted) + len(rejected), 1), 6),
        "providers": dict(sorted(providers.items())),
        "provider_errors": dict(provider_errors.most_common()),
        "quality_tiers": dict(sorted(quality_tiers.items())),
        "collection_modes": dict(sorted(collection_modes.items())),
        "runs_with_policy_corrections": runs_with_policy_corrections,
        "policy_correction_events": policy_correction_events,
        "rate_limit_failures": sum(
            "rate" in key.casefold() or "usage_limit" in key.casefold() for key in provider_errors.elements()
        ),
        "capability_distribution": dict(sorted(capabilities.items())),
        "unique_source_groups": len(source_groups),
        "largest_source_group_share": round(max(source_groups.values(), default=0) / max(len(accepted), 1), 6),
        "unique_path_signatures": len(path_signatures),
        "largest_path_share": round(max(path_signatures.values(), default=0) / max(len(accepted), 1), 6),
        "average_turns": round(sum(turn_counts) / max(len(turn_counts), 1), 6),
        "average_tool_calls": round(sum(tool_call_counts) / max(len(tool_call_counts), 1), 6),
        "average_provider_latency_seconds": round(sum(latencies) / max(len(latencies), 1), 6),
        "token_usage": dict(sorted(usage_totals.items())),
        "estimated_cost": "NOT_AVAILABLE_UNLESS_PROVIDER_REPORTS_COST",
        "failure_taxonomy": dict(failure_taxonomy.most_common()),
        "task_schema_versions": dict(sorted(task_schema_versions.items())),
        "accepted_sha256": sha256(root / "accepted.jsonl"),
        "rejected_sha256": sha256(root / "rejected.jsonl"),
    }
    (root / "audit.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                **manifest,
                "task_specs_sha256": sha256(root / "task_specs.jsonl"),
                "task_manifest_sha256": (
                    sha256(root / "task-specs.manifest.json") if (root / "task-specs.manifest.json").is_file() else None
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "capability_distribution.json").write_text(
        json.dumps(dict(sorted(capabilities.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "failure_taxonomy.json").write_text(
        json.dumps(dict(failure_taxonomy.most_common()), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT / "datasets/interim/studyhub_teacher_v2_2")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = verify_root(args.root)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
