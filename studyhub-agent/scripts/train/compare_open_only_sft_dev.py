#!/usr/bin/env python3
"""Compare Base, Mixed-v3.0, and Open-Only Benchmark v2 Development runs."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.train.compare_base_sft_dev import load_jsonl, metric, paired_bootstrap, sha256

CAPABILITY_SLICES: dict[str, set[str]] = {
    "factual_retrieval": {"factual_passage_retrieval"},
    "multi_hop": {"cross_chunk_synthesis", "multi_source_synthesis"},
    "citation_grounding": {
        "factual_passage_retrieval",
        "cross_chunk_synthesis",
        "multi_source_synthesis",
    },
    "web": {"authentic_web_research", "memory_web_composition"},
    "memory": {
        "memory_absence",
        "memory_collective_conflict",
        "memory_collective_low_confidence",
        "memory_cross_user_privacy",
        "memory_current_conflict",
        "memory_incomplete_abstention",
        "memory_irrelevant_tool_abstention",
        "memory_rag_composition",
        "memory_scope_resolution",
        "memory_selection",
        "memory_temporal_change",
        "memory_user_correction",
        "memory_web_composition",
    },
    "state_function": {"state_function_calling", "state_multistep_postcondition"},
    "recovery": {
        "permission_avoidance",
        "permission_recovery",
        "query_reformulation",
        "tool_failure_recovery",
    },
    "direct_answer_abstention": {
        "direct_answer_tool_relevance",
        "insufficient_evidence",
        "memory_incomplete_abstention",
        "memory_irrelevant_tool_abstention",
    },
    "stop_cost_control": {"stop_cost_control"},
}

SEARCH_READ_PAIRS = {
    "knowledge_search": "knowledge_read",
    "web_search": "web_fetch",
}

EVIDENCE_RESULT_FIELDS = {
    "knowledge_search": "results",
    "knowledge_browse": "results",
    "web_search": "results",
    "personal_memory_search": "memories",
    "collective_memory_search": "results",
}

PREMATURE_PROCESS_FAILURES = {
    "premature_final",
    "required_tool_missing",
    "realized_horizon_too_short",
}


def _summary(path: Path) -> dict[str, Any]:
    return json.loads((path / "summary.json").read_text(encoding="utf-8"))


def _error_codes(row: dict[str, Any]) -> set[str]:
    evaluation = row.get("evaluation", {})
    trace = row.get("trace", {})
    codes = {str(value) for value in evaluation.get("hard_gate_reasons", [])}
    for namespace in ("policy_errors", "environment_errors", "runtime_errors"):
        codes.update(str(value) for value in trace.get(namespace, []))
    normalized = set(codes)
    normalized.update(value.split(":", 1)[-1] for value in codes)
    return normalized


def _successful_call(call: dict[str, Any]) -> bool:
    if call.get("error"):
        return False
    observation = call.get("observation")
    return isinstance(observation, dict) and observation.get("ok", True) is not False


def _evidence_gain(call: dict[str, Any]) -> bool:
    if not _successful_call(call):
        return False
    name = str(call.get("name", ""))
    observation = call["observation"]
    result_field = EVIDENCE_RESULT_FIELDS.get(name)
    if result_field:
        return bool(observation.get(result_field))
    if name == "knowledge_read":
        return bool(observation.get("text"))
    if name == "web_fetch":
        return bool(observation.get("text") or observation.get("content"))
    if name == "learning_profile_get":
        return bool(observation.get("profile"))
    return False


def _search_read_conversion(calls: list[dict[str, Any]]) -> tuple[bool, bool]:
    successful_searches = [
        (index, SEARCH_READ_PAIRS[str(call.get("name"))])
        for index, call in enumerate(calls)
        if str(call.get("name")) in SEARCH_READ_PAIRS and _successful_call(call)
    ]
    if not successful_searches:
        return False, False
    converted = any(
        later_index > search_index and str(later_call.get("name")) == expected_read and _successful_call(later_call)
        for search_index, expected_read in successful_searches
        for later_index, later_call in enumerate(calls)
    )
    return True, converted


def _premature_final(row: dict[str, Any]) -> bool:
    process = row.get("evaluation", {}).get("diagnostics", {}).get("process", {})
    failures = {str(value) for value in process.get("requirement_failures", [])}
    return bool(failures & PREMATURE_PROCESS_FAILURES) or "premature_final" in _error_codes(row)


def _selected_failure_counts(rows: dict[str, dict[str, Any]]) -> dict[str, int]:
    aliases = {
        "invalid_citation": {"invalid_citation"},
        "source_not_discovered": {"source_not_discovered"},
        "invalid_arguments": {
            "argument_validation_error",
            "invalid_arguments",
            "invalid_tool_arguments",
        },
        "tool_budget_exhausted": {
            "max_tool_calls",
            "tool_budget_exhausted",
        },
    }
    result = Counter({name: 0 for name in aliases})
    result["empty_final"] = 0
    result["premature_final"] = 0
    for row in rows.values():
        codes = _error_codes(row)
        for name, accepted_codes in aliases.items():
            result[name] += bool(codes & accepted_codes)
        result["empty_final"] += not str(row.get("final_answer", "")).strip()
        result["premature_final"] += _premature_final(row)
    return dict(result)


def _behavior_metrics(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    tool_counts: list[int] = []
    evidence_gains = 0
    successful_policy_steps = 0
    search_tasks = 0
    converted_tasks = 0
    tool_names: Counter[str] = Counter()
    for row in rows.values():
        calls = row.get("trace", {}).get("tool_calls", [])
        tool_counts.append(len(calls))
        tool_names.update(str(call.get("name", "")) for call in calls)
        evidence_gains += sum(_evidence_gain(call) for call in calls)
        successful_policy_steps += int(row.get("evaluation", {}).get("realized_successful_policy_steps", 0))
        has_search, converted = _search_read_conversion(calls)
        search_tasks += has_search
        converted_tasks += converted
    task_count = len(rows)
    return {
        "zero_tool_final_count": sum(value == 0 for value in tool_counts),
        "zero_tool_final_rate": round(sum(value == 0 for value in tool_counts) / task_count, 6),
        "one_tool_final_count": sum(value == 1 for value in tool_counts),
        "one_tool_final_rate": round(sum(value == 1 for value in tool_counts) / task_count, 6),
        "premature_final_count": sum(_premature_final(row) for row in rows.values()),
        "premature_final_rate": round(
            sum(_premature_final(row) for row in rows.values()) / task_count,
            6,
        ),
        "successful_evidence_gain_steps": evidence_gains,
        "successful_evidence_gain_steps_per_task": round(evidence_gains / task_count, 6),
        "successful_policy_steps": successful_policy_steps,
        "successful_policy_steps_per_task": round(successful_policy_steps / task_count, 6),
        "search_tasks": search_tasks,
        "search_to_read_converted_tasks": converted_tasks,
        "search_to_read_conversion_rate": round(
            converted_tasks / search_tasks if search_tasks else 0.0,
            6,
        ),
        "tool_name_counts": dict(sorted(tool_names.items())),
    }


def _capability_slices(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for name, capabilities in CAPABILITY_SLICES.items():
        selected = [row for row in rows.values() if str(row.get("capability_id")) in capabilities]
        if not selected:
            result[name] = {"tasks": 0, "strict_count": 0, "strict_rate": None}
            continue
        strict_count = sum(bool(row.get("evaluation", {}).get("strict_success")) for row in selected)
        result[name] = {
            "tasks": len(selected),
            "strict_count": strict_count,
            "strict_rate": round(strict_count / len(selected), 6),
            "mean_diagnostic": round(
                statistics.fmean(metric(row, "diagnostic") for row in selected),
                6,
            ),
        }
    return result


def _run_metrics(
    run_dir: Path,
    summary: dict[str, Any],
    rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    strict_count = sum(bool(row.get("evaluation", {}).get("strict_success")) for row in rows.values())
    return {
        "run_id": summary.get("run_id"),
        "model": summary.get("model"),
        "tasks": len(rows),
        "strict_count": strict_count,
        "strict_success_rate": round(strict_count / len(rows), 6),
        "mean_diagnostic_score": summary.get("mean_score"),
        "mean_tool_calls": summary.get("tool_calls", {}).get("mean"),
        "mean_latency_seconds": summary.get("latency_seconds", {}).get("mean"),
        "infra_excluded": summary.get("infra_excluded"),
        "episodes_sha256": sha256(run_dir / "episodes.jsonl"),
        "failures": _selected_failure_counts(rows),
        "behavior": _behavior_metrics(rows),
        "capability_slices": _capability_slices(rows),
    }


def _paired_contrast(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    *,
    seed: int,
) -> dict[str, Any]:
    task_ids = sorted(before)
    pairs = [
        (metric(before[task_id], "strict_success"), metric(after[task_id], "strict_success")) for task_id in task_ids
    ]
    return {
        "wins": sum(left == 0 and right == 1 for left, right in pairs),
        "losses": sum(left == 1 and right == 0 for left, right in pairs),
        "ties": sum(left == right for left, right in pairs),
        "strict_delta": paired_bootstrap(
            task_ids,
            lambda key: metric(after[key], "strict_success") - metric(before[key], "strict_success"),
            seed=seed,
        ),
        "diagnostic_delta": paired_bootstrap(
            task_ids,
            lambda key: metric(after[key], "diagnostic") - metric(before[key], "diagnostic"),
            seed=seed + 1,
        ),
        "mean_tool_calls_delta": round(
            statistics.fmean(metric(after[key], "tool_calls") - metric(before[key], "tool_calls") for key in task_ids),
            6,
        ),
    }


def compare(
    base_dir: Path,
    mixed_dir: Path,
    open_dir: Path,
    *,
    seed: int,
    control_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    directories = {"base": base_dir, "mixed_v3": mixed_dir, "open_only": open_dir}
    summaries = {name: _summary(path) for name, path in directories.items()}
    rows = {name: load_jsonl(path / "episodes.jsonl") for name, path in directories.items()}
    failures: list[str] = []

    benchmark_hashes = {value.get("benchmark_manifest_sha256") for value in summaries.values()}
    task_sets = {tuple(sorted(value)) for value in rows.values()}
    for name, summary in summaries.items():
        if summary.get("mode") != "development":
            failures.append(f"{name}:mode_not_development")
        if float(summary.get("temperature", -1)) != 0.0:
            failures.append(f"{name}:temperature_not_zero")
        if int(summary.get("infra_excluded", -1)) != 0:
            failures.append(f"{name}:infra_exclusions_present")
    if len(benchmark_hashes) != 1:
        failures.append("benchmark_hash_mismatch")
    if len(task_sets) != 1:
        failures.append("paired_task_set_mismatch")
    if any(len(value) != 51 for value in rows.values()):
        failures.append("paired_task_count_not_51")
    sealed_rows = sum(
        bool(row.get("evaluation", {}).get("diagnostics", {}).get("sealed"))
        for run_rows in rows.values()
        for row in run_rows.values()
    )
    if sealed_rows:
        failures.append(f"sealed_rows:{sealed_rows}")

    run_metrics = {name: _run_metrics(directories[name], summaries[name], rows[name]) for name in directories}
    pairwise = {
        "mixed_vs_base": _paired_contrast(rows["base"], rows["mixed_v3"], seed=seed),
        "open_vs_base": _paired_contrast(rows["base"], rows["open_only"], seed=seed + 10),
        "open_vs_mixed": _paired_contrast(rows["mixed_v3"], rows["open_only"], seed=seed + 20),
    }

    base = run_metrics["base"]
    mixed = run_metrics["mixed_v3"]
    open_only = run_metrics["open_only"]
    base_tool_calls = float(base["mean_tool_calls"])
    tool_call_change = (float(open_only["mean_tool_calls"]) - base_tool_calls) / base_tool_calls
    gates = {
        "open_strict_gte_base": open_only["strict_count"] >= base["strict_count"],
        "open_strict_gt_mixed": open_only["strict_count"] > mixed["strict_count"],
        "paired_wins_gt_losses_vs_mixed": pairwise["open_vs_mixed"]["wins"] > pairwise["open_vs_mixed"]["losses"],
        "mean_diagnostic_gt_mixed": float(open_only["mean_diagnostic_score"]) > float(mixed["mean_diagnostic_score"]),
        "factual_retrieval_not_below_base_by_more_than_one": open_only["capability_slices"]["factual_retrieval"][
            "strict_count"
        ]
        >= base["capability_slices"]["factual_retrieval"]["strict_count"] - 1,
        "invalid_citation_not_more_than_base_plus_one": open_only["failures"]["invalid_citation"]
        <= base["failures"]["invalid_citation"] + 1,
        "tool_calls_no_unrewarded_drop_gt_15pct": tool_call_change >= -0.15
        or open_only["strict_count"] > base["strict_count"],
    }
    diagnostic_gate_pass = not failures and all(gates.values())
    control_status = control_audit.get("status") if control_audit else "MISSING"
    if control_status != "PASS":
        failures.append(f"training_control_contract:{control_status}")
    directional_gate_pass = diagnostic_gate_pass and control_status == "PASS"
    if directional_gate_pass:
        conclusion = "OPEN_ONLY_DIRECTION_POSITIVE"
    elif diagnostic_gate_pass:
        conclusion = "CONTROL_CONTRACT_FAILED_LR_SCHEDULE"
    elif open_only["strict_count"] > mixed["strict_count"] and open_only["strict_count"] < base["strict_count"]:
        conclusion = "OPEN_ONLY_BETTER_THAN_MIXED_BUT_BELOW_BASE"
    else:
        conclusion = "OPEN_ONLY_NO_BENEFIT"

    return {
        "schema_version": "studyhub.open-only-development-comparison.v1",
        "status": "PASS" if not failures else "FAIL",
        "conclusion": conclusion,
        "diagnostic_conclusion": ("OPEN_ONLY_DIRECTION_POSITIVE" if diagnostic_gate_pass else "OPEN_ONLY_NO_BENEFIT"),
        "claim": "DIRECTIONAL_PAIRED_EVIDENCE_ONLY",
        "benchmark_manifest_sha256": next(iter(benchmark_hashes)) if len(benchmark_hashes) == 1 else None,
        "sealed_used": False,
        "runs": run_metrics,
        "pairwise": pairwise,
        "directional_gates": {
            "status": "PASS" if directional_gate_pass else "FAIL",
            "diagnostic_status": "PASS" if diagnostic_gate_pass else "FAIL",
            "checks": gates,
            "open_vs_base_tool_call_change_fraction": round(tool_call_change, 6),
        },
        "training_control_contract": control_audit,
        "limitations": [
            "The 51-task Development split supports directional paired evidence, "
            "not a small-effect significance claim.",
            "Capability slices with one or a few tasks are descriptive only.",
            "No Sealed-A/B or external benchmark result is used.",
            "Successful evidence gain is a deterministic trace diagnostic, not a learned reward.",
        ],
        "failures": failures,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-run", type=Path, required=True)
    parser.add_argument("--mixed-run", type=Path, required=True)
    parser.add_argument("--open-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--control-audit", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260827)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    control_audit = json.loads(args.control_audit.read_text(encoding="utf-8"))
    result = compare(
        args.base_run,
        args.mixed_run,
        args.open_run,
        seed=args.seed,
        control_audit=control_audit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": result["status"],
                "conclusion": result["conclusion"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
