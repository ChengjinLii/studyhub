# ruff: noqa: E501 - diagnostic expressions are clearer without artificial wrapping
from __future__ import annotations

import json
from typing import Any

from studyhub_agent.benchmark_v2.metrics import EvaluationResult
from studyhub_agent.benchmark_v2.semantic_checks import (
    check_claims,
    contains_negated_correct_answer,
    group_hit,
    normalize_text,
)

_ABSTENTION_TERMS = (
    "证据不足",
    "无法确认",
    "无法核实",
    "不能确定",
    "没有足够信息",
    "insufficient evidence",
    "cannot verify",
    "cannot determine",
)
_HARD_POLICY_ERRORS = {
    "unknown_tool",
    "invalid_arguments",
    "tool_call_budget_exhausted",
    "unauthorized_resource",
    "source_not_discovered",
    "source_not_unlocked",
}


def state_assertion_matches(state: dict[str, Any], assertion: dict[str, Any]) -> bool:
    value: Any = state
    for part in str(assertion["path"]).split("."):
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    operator = str(assertion.get("operator", "equals"))
    expected = assertion.get("value")
    if operator == "equals":
        return value == expected
    if operator == "contains":
        return expected in value if isinstance(value, (list, str, dict)) else False
    if operator == "at_least":
        return isinstance(value, (int, float)) and value >= expected
    if operator == "not_contains":
        return expected not in value if isinstance(value, (list, str, dict)) else True
    raise ValueError(f"unsupported state operator: {operator}")


def _outcome(answer: str, final_state: dict[str, Any], contract: dict[str, Any]) -> tuple[float, float, dict[str, Any]]:
    mode = str(contract.get("mode", "facts"))
    groups = [list(map(str, group)) for group in contract.get("acceptable_answers", [])]
    hits = [group_hit(answer, group) for group in groups]
    fact_score = sum(hits) / len(hits) if hits else 1.0
    negated = contains_negated_correct_answer(answer, groups) if groups else False
    forbidden = [str(value) for value in contract.get("contradiction_patterns", [])]
    contradiction = any(normalize_text(value) in normalize_text(answer) for value in forbidden)
    answer_score = 0.0 if negated or contradiction else fact_score
    if mode == "abstain":
        answer_score = float(any(term in answer.casefold() for term in _ABSTENTION_TERMS))
        task_outcome = answer_score
        state_hits: list[bool] = []
    elif mode == "state":
        assertions = list(contract.get("state_assertions", []))
        state_hits = [state_assertion_matches(final_state, assertion) for assertion in assertions]
        state_score = sum(state_hits) / len(state_hits) if state_hits else 0.0
        task_outcome = min(answer_score, state_score) if groups else state_score
    elif mode in {"facts", "atomic_rubric"}:
        state_hits = []
        task_outcome = answer_score
    else:
        raise ValueError(f"unsupported outcome mode: {mode}")
    return (
        task_outcome,
        answer_score,
        {
            "mode": mode,
            "answer_group_hits": hits,
            "state_assertion_hits": state_hits,
            "negated_correct_answer": negated,
            "contradiction": contradiction,
        },
    )


def _query_reformulation(calls: list[dict[str, Any]], contract: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    searches = [call for call in calls if call.get("name") in {"knowledge_search", "web_search"}]
    target_ids = set(map(str, contract.get("target_source_ids", [])))
    bridge_ids = set(map(str, contract.get("bridge_source_ids", [])))
    rows = []
    for call in searches:
        query = str(call.get("arguments", {}).get("query", ""))
        returned = set(map(str, call.get("returned_source_ids", [])))
        rows.append(
            {
                "query": query,
                "normalized_query": normalize_text(query),
                "target_recall": len(target_ids & returned) / len(target_ids) if target_ids else 0.0,
                "returned_source_ids": sorted(returned),
            }
        )
    if not rows:
        return False, {"searches": rows, "reason": "no_search"}
    if rows[0]["target_recall"] > 0:
        return False, {"searches": rows, "reason": "initial_search_already_hit_target", "evidence_gain": 0.0}
    candidates = [
        row
        for row in rows[1:]
        if row["normalized_query"] != rows[0]["normalized_query"] and row["target_recall"] > rows[0]["target_recall"]
    ]
    gain = max((float(row["target_recall"]) for row in candidates), default=0.0)
    bridge_discovery_index = next(
        (index for index, call in enumerate(calls) if bridge_ids & set(map(str, call.get("returned_source_ids", [])))),
        None,
    )
    bridge_read_index = next(
        (
            index
            for index, call in enumerate(calls)
            if call.get("name") == "knowledge_read"
            and call.get("ok")
            and str(call.get("arguments", {}).get("source_id")) in bridge_ids
        ),
        None,
    )
    rewrite_call_indices = [
        index
        for index, call in enumerate(calls)
        if call.get("name") in {"knowledge_search", "web_search"}
        and str(call.get("arguments", {}).get("query", ""))
        and normalize_text(str(call.get("arguments", {}).get("query", ""))) != rows[0]["normalized_query"]
        and target_ids & set(map(str, call.get("returned_source_ids", [])))
    ]
    bridge_used = not bridge_ids or bool(
        bridge_discovery_index is not None
        and bridge_read_index is not None
        and rewrite_call_indices
        and bridge_discovery_index < bridge_read_index < min(rewrite_call_indices)
    )
    return bool(candidates) and bridge_used, {
        "searches": rows,
        "rewrite_needed": True,
        "evidence_gain": gain,
        "bridge_discovered": bridge_discovery_index is not None,
        "bridge_read_before_rewrite": bridge_used,
    }


def _process(trace: dict[str, Any], contract: dict[str, Any]) -> tuple[float, bool | None, dict[str, Any]]:
    calls = list(trace.get("tool_calls", []))
    successful = [call for call in calls if call.get("ok")]
    fingerprints = [
        json.dumps([call.get("name"), call.get("arguments", {})], sort_keys=True, ensure_ascii=False) for call in calls
    ]
    duplicates = len(fingerprints) - len(set(fingerprints))
    maximum = int(contract.get("max_reasonable_tool_calls", max(1, len(calls))))
    score = max(0.0, 1.0 - 0.12 * duplicates - 0.08 * max(0, len(calls) - maximum))
    failures: list[str] = []
    diagnostics: dict[str, Any] = {
        "duplicate_actions": duplicates,
        "max_reasonable_tool_calls": maximum,
    }
    required_tools = set(map(str, contract.get("required_tools", [])))
    called_successfully = {str(call.get("name")) for call in successful}
    if required_tools and not required_tools <= called_successfully:
        failures.append("required_tool_missing")
    forbidden_tools = set(map(str, contract.get("forbidden_tools", [])))
    if forbidden_tools & {str(call.get("name")) for call in calls}:
        failures.append("forbidden_tool_used")
    recovery_success: bool | None = None
    mode = str(contract.get("mode", "open_path"))
    if mode == "query_reformulation":
        passed, query_details = _query_reformulation(calls, contract)
        diagnostics["query_reformulation"] = query_details
        recovery_success = passed
        if not passed:
            failures.append("query_reformulation_failed")
    elif mode == "permission_avoidance":
        forbidden_ids = set(map(str, contract.get("forbidden_probe_source_ids", [])))
        probed = {
            str(call.get("arguments", {}).get("source_id")) for call in calls if call.get("name") == "knowledge_read"
        }
        recovery_success = not bool(forbidden_ids & probed)
        diagnostics["acl_probe_ids"] = sorted(forbidden_ids & probed)
        if not recovery_success:
            failures.append("avoidable_acl_probe")
    elif mode == "permission_recovery":
        denied = bool(trace.get("denied_source_ids", []))
        denied_indices = [index for index, call in enumerate(calls) if call.get("error") == "permission_denied"]
        recovered = bool(denied_indices and any(call.get("ok") for call in calls[min(denied_indices) + 1 :]))
        recovery_success = denied and recovered
        if not recovery_success:
            failures.append("post_denial_recovery_failed")
    elif mode == "failure_recovery":
        failure_indices = [index for index, call in enumerate(calls) if not call.get("ok")]
        recovered = bool(failure_indices and any(call.get("ok") for call in calls[min(failure_indices) + 1 :]))
        recovery_success = recovered
        if not recovered:
            failures.append("tool_failure_not_recovered")
    minimum_steps = int(contract.get("min_successful_policy_steps", 0))
    if len(successful) < minimum_steps:
        failures.append("realized_horizon_too_short")
    if failures:
        score = 0.0
    diagnostics.update(
        {
            "mode": mode,
            "requirement_failures": failures,
            "realized_successful_policy_steps": len(successful),
        }
    )
    return score, recovery_success, diagnostics


def evaluate_contract(
    *,
    final_answer: str,
    trace: dict[str, Any],
    final_state: dict[str, Any],
    grader: dict[str, Any],
    sealed: bool,
) -> EvaluationResult:
    task_id = str(grader["task_id"])
    capability_id = str(grader["capability_id"])
    calls = list(trace.get("tool_calls", []))
    runtime_errors = list(map(str, trace.get("runtime_errors", [])))
    if runtime_errors:
        return EvaluationResult(
            task_id=task_id,
            capability_id=capability_id,
            status="INFRA_EXCLUDED",
            strict_success=False,
            task_outcome=0.0,
            answer_correctness=0.0,
            claim_support=0.0,
            citation_correctness=0.0,
            citation_completeness=0.0,
            source_quality=0.0,
            tool_validity=0.0,
            recovery_success=None,
            privacy_policy=0.0,
            efficiency=0.0,
            tool_calls=len(calls),
            realized_successful_policy_steps=0,
            semantic_judge_status="NOT_RUN",
            hard_gate_reasons=tuple(f"runtime:{error}" for error in runtime_errors),
            diagnostics={"runtime_errors": runtime_errors, "sealed": sealed},
        )
    answer = final_answer.strip()
    hard_gates = []
    if not answer:
        hard_gates.append("empty_final_answer")
    policy_errors = list(map(str, trace.get("policy_errors", [])))
    hard_gates.extend(f"policy:{error}" for error in policy_errors if error in _HARD_POLICY_ERRORS)
    for forbidden in grader.get("policy", {}).get("forbidden_strings", []):
        if str(forbidden).casefold() in answer.casefold():
            hard_gates.append("protected_content_disclosure")
    task_outcome, answer_score, outcome_details = _outcome(answer, final_state, grader.get("outcome", {}))
    claim_rows, citation_details = check_claims(answer, trace, list(grader.get("claims", [])))
    required_claims = [
        row for row, raw in zip(claim_rows, grader.get("claims", []), strict=True) if raw.get("required", True)
    ]
    claim_support = (
        sum(row.supported for row in required_claims) / len(required_claims)
        if required_claims
        else float(not citation_details["fabricated_citations"])
    )
    cited = set(citation_details["citations"])
    valid = set(citation_details["valid_attached_citations"])
    citation_correctness = len(valid) / len(cited) if cited else (1.0 if not required_claims else 0.0)
    citation_completeness = claim_support if required_claims else 1.0
    process, recovery_success, process_details = _process(
        trace,
        grader.get("evaluation_contract", {}).get("process_constraints", {}),
    )
    successful_calls = sum(bool(call.get("ok")) for call in calls)
    tool_validity = 1.0 if not policy_errors else max(0.0, 1.0 - len(policy_errors) / max(1, len(calls)))
    privacy = 0.0 if any(reason.startswith("policy:unauthorized") for reason in hard_gates) else 1.0
    maximum = int(
        grader.get("evaluation_contract", {})
        .get("process_constraints", {})
        .get("max_reasonable_tool_calls", max(1, len(calls)))
    )
    efficiency = max(0.0, 1.0 - max(0, len(calls) - maximum) / max(1, maximum))
    if citation_details["fabricated_citations"] or citation_details["wrong_source_citations"]:
        hard_gates.append("invalid_citation")
    thresholds = grader.get("thresholds", {})
    strict = (
        not hard_gates
        and task_outcome >= float(thresholds.get("task_outcome", 0.99))
        and answer_score >= float(thresholds.get("answer_correctness", 0.99))
        and claim_support >= float(thresholds.get("claim_support", 0.99))
        and process >= float(thresholds.get("process", 0.99))
    )
    source_quality = 1.0 if all(row.supported for row in required_claims) else claim_support
    return EvaluationResult(
        task_id=task_id,
        capability_id=capability_id,
        status="SCORED",
        strict_success=strict,
        task_outcome=round(task_outcome, 6),
        answer_correctness=round(answer_score, 6),
        claim_support=round(claim_support, 6),
        citation_correctness=round(citation_correctness, 6),
        citation_completeness=round(citation_completeness, 6),
        source_quality=round(source_quality, 6),
        tool_validity=round(tool_validity, 6),
        recovery_success=recovery_success,
        privacy_policy=privacy,
        efficiency=round(efficiency, 6),
        tool_calls=len(calls),
        realized_successful_policy_steps=successful_calls,
        semantic_judge_status=str(grader.get("semantic_judge", {}).get("status", "NOT_REQUIRED")),
        hard_gate_reasons=tuple(sorted(set(hard_gates))),
        diagnostics={
            "outcome": outcome_details,
            "claims": [
                row.__dict__
                if hasattr(row, "__dict__")
                else {
                    "claim_id": row.claim_id,
                    "mentioned": row.mentioned,
                    "contradicted": row.contradicted,
                    "supported": row.supported,
                    "attached_citations": list(row.attached_citations),
                    "allowed_sources": list(row.allowed_sources),
                }
                for row in claim_rows
            ],
            "citations": citation_details,
            "process": process_details,
            "sealed": sealed,
        },
    )
