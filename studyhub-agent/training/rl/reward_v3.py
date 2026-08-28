from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

REWARD_VERSION = "reward-v3.0.0"
INFRA_STATUS = "INFRA_EXCLUDED"
SCORED_STATUS = "SCORED"

_LATIN_OR_NUMBER = re.compile(r"[a-z0-9]+")
_CHINESE = re.compile(r"[\u3400-\u9fff]")
_CITATION = re.compile(r"\[([^\[\]\s]{2,240})\]")
_UNCERTAINTY_TERMS = (
    "证据不足",
    "无法确认",
    "不能确定",
    "暂无可靠",
    "insufficient evidence",
    "insufficient",
    "cannot verify",
    "cannot determine",
    "not enough evidence",
)
_FACTUAL_NON_ANSWER_TERMS = (
    "尚未作答",
    "未给出结论",
    "没有给出结论",
    "not answered",
    "no answer given",
)
_DEFAULT_HARD_POLICY_ERRORS = frozenset(
    {
        "unknown_tool",
        "invalid_arguments",
        "fixture_route_not_found",
        "unauthorized_resource",
        "source_not_discovered",
        "source_not_unlocked",
        "tool_call_budget_exhausted",
        "url_not_in_replay_snapshot",
        "url_not_discovered",
        "cross_user_memory_access",
        "private_data_disclosure",
    }
)


@dataclass(frozen=True, slots=True)
class RewardV3Result:
    status: str
    total: float
    strict_success: bool
    eligible_for_policy_update: bool
    hard_constraints: float
    objective_end_state: float
    semantic_rubric: float
    grounding: float
    process_quality: float
    tool_validity: float
    efficiency: float
    evidence_gain: float
    recovery: float | None
    hard_gate_triggered: bool
    hard_gate_reasons: tuple[str, ...]
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tokens(value: Any) -> list[str]:
    normalized = str(value or "").casefold()
    return [*_LATIN_OR_NUMBER.findall(normalized), *_CHINESE.findall(normalized)]


def _normalized(value: Any) -> str:
    return " ".join(_tokens(value))


def _contains_phrase(value: str, phrase: Any) -> bool:
    phrase_text = str(phrase or "").strip().casefold()
    if not phrase_text:
        return False
    candidate = value.casefold()
    if re.fullmatch(r"[a-z0-9]", phrase_text):
        if _normalized(candidate) == phrase_text:
            return True
        answer_pattern = re.compile(
            rf"(?:答案|选项|answer|option)\s*(?:是|为|[:：])?\s*"
            rf"[（(\[]?{re.escape(phrase_text)}(?:[）)\]]|\b)",
            re.IGNORECASE,
        )
        return bool(answer_pattern.search(candidate))
    if phrase_text in candidate:
        return True
    expected_tokens = _tokens(phrase_text)
    candidate_tokens = set(_tokens(candidate))
    return bool(expected_tokens) and all(token in candidate_tokens for token in expected_tokens)


def _group_score(value: str, groups: Iterable[Iterable[Any]]) -> tuple[float, list[bool]]:
    outcomes = [any(_contains_phrase(value, alias) for alias in group) for group in groups]
    if not outcomes:
        return 1.0, []
    return sum(outcomes) / len(outcomes), outcomes


def _path_get(value: Any, path: str | list[Any]) -> tuple[bool, Any]:
    parts = path if isinstance(path, list) else [part for part in str(path).split(".") if part]
    current = value
    for part in parts:
        if isinstance(current, dict) and str(part) in current:
            current = current[str(part)]
        elif isinstance(current, list) and isinstance(part, int) and 0 <= part < len(current):
            current = current[part]
        else:
            return False, None
    return True, current


def _state_assertion(state: dict[str, Any], assertion: dict[str, Any]) -> bool:
    present, actual = _path_get(state, assertion.get("path", ""))
    operator = str(assertion.get("operator", "eq"))
    expected = assertion.get("value")
    if operator == "exists":
        return present == bool(expected)
    if not present:
        return False
    if operator == "eq":
        return actual == expected
    if operator == "contains":
        return expected in actual if isinstance(actual, (list, str, dict)) else False
    if operator == "contains_all":
        return isinstance(actual, (list, set, tuple)) and set(expected or []) <= set(actual)
    if operator == "gte":
        try:
            return float(actual) >= float(expected)
        except (TypeError, ValueError):
            return False
    if operator == "lte":
        try:
            return float(actual) <= float(expected)
        except (TypeError, ValueError):
            return False
    raise ValueError(f"unsupported state assertion operator: {operator}")


def _objective_score(
    final_answer: str,
    final_state: dict[str, Any],
    objective: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    mode = str(objective.get("mode", "facts"))
    answer_groups = list(objective.get("acceptable_answers", []))
    facts_score, facts_matches = _group_score(final_answer, answer_groups)
    if mode == "facts" and any(term in final_answer.casefold() for term in _FACTUAL_NON_ANSWER_TERMS):
        facts_score = 0.0
    assertions = list(objective.get("state_assertions", []))
    assertion_matches = [_state_assertion(final_state, row) for row in assertions]
    state_score = sum(assertion_matches) / len(assertion_matches) if assertion_matches else 1.0
    details: dict[str, Any] = {
        "mode": mode,
        "facts_matches": facts_matches,
        "state_assertion_matches": assertion_matches,
    }
    if mode == "facts":
        score = facts_score
    elif mode == "state":
        score = state_score
    elif mode == "facts_and_state":
        score = min(facts_score, state_score)
    elif mode == "abstain":
        has_uncertainty = any(term in final_answer.casefold() for term in _UNCERTAINTY_TERMS)
        forbidden_specifics = list(objective.get("forbidden_specifics", []))
        leaked = [term for term in forbidden_specifics if _contains_phrase(final_answer, term)]
        score = float(has_uncertainty and not leaked)
        details.update({"uncertainty_present": has_uncertainty, "forbidden_specifics": leaked})
    elif mode == "successful_tool_outcome":
        minimum = int(objective.get("minimum_successful_tool_calls", 1))
        successful = int(objective.get("observed_successful_tool_calls", 0))
        score = min(1.0, successful / max(1, minimum))
        if answer_groups:
            score = min(score, facts_score)
    else:
        raise ValueError(f"unsupported objective mode: {mode}")
    return round(max(0.0, min(1.0, score)), 6), details


def _sentences(value: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[。！？!?;；\n])", value) if part.strip()]
    sentences: list[str] = []
    leading_citations = re.compile(
        r"^((?:\[[^\[\]\s]{2,240}\]\s*)+)([。！？!?;；]?)(.*)$",
        re.DOTALL,
    )
    for part in parts:
        match = leading_citations.match(part)
        if sentences and match:
            citations, delimiter, remainder = match.groups()
            sentences[-1] = f"{sentences[-1]}{citations.strip()}{delimiter}"
            if remainder.strip():
                sentences.append(remainder.strip())
            continue
        sentences.append(part)
    return sentences


def _citation_details(final_answer: str, trace: dict[str, Any]) -> dict[str, Any]:
    citations = set(_CITATION.findall(final_answer))
    read = set(map(str, trace.get("read_source_ids", [])))
    invalid = sorted(citations - read)
    return {
        "citations": sorted(citations),
        "read_source_ids": sorted(read),
        "invalid_citations": invalid,
        "precision": (len(citations - set(invalid)) / len(citations) if citations else 1.0),
    }


def _claim_grounding(
    final_answer: str,
    trace: dict[str, Any],
    claims: list[dict[str, Any]],
) -> tuple[float, dict[str, Any]]:
    citation_details = _citation_details(final_answer, trace)
    citation_contract_active = any(
        bool(claim.get("citation_required", bool(claim.get("support_source_ids")))) for claim in claims
    )
    read = set(citation_details["read_source_ids"])
    rows = []
    all_citations = set(citation_details["citations"])
    for claim in claims:
        groups = list(claim.get("acceptable_semantic_answers", []))
        mentioned_score, mentioned_groups = _group_score(final_answer, groups)
        mentioned = mentioned_score >= float(claim.get("minimum_semantic_coverage", 1.0))
        contradictions = [
            pattern for pattern in claim.get("contradiction_patterns", []) if _contains_phrase(final_answer, pattern)
        ]
        allowed = set(map(str, claim.get("support_source_ids", [])))
        citation_required = bool(claim.get("citation_required", bool(allowed)))
        attached: set[str] = set()
        for sentence in _sentences(final_answer):
            sentence_score, _ = _group_score(sentence, groups)
            if sentence_score >= float(claim.get("minimum_semantic_coverage", 1.0)):
                attached.update(_CITATION.findall(sentence))
        if mentioned and len(claims) == 1 and not attached:
            # A single semantic claim may span semicolon-delimited clauses with
            # citations collected at the end of the answer.
            attached.update(all_citations)
        supported_citations = attached & allowed & read
        citation_ok = bool(supported_citations) if citation_required else not bool(attached - read)
        supported = mentioned and not contradictions and citation_ok
        rows.append(
            {
                "claim_id": str(claim.get("claim_id", len(rows))),
                "required": bool(claim.get("required", True)),
                "mentioned": mentioned,
                "semantic_groups": mentioned_groups,
                "contradictions": contradictions,
                "attached_citations": sorted(attached),
                "supported_citations": sorted(supported_citations),
                "supported": supported,
            }
        )
    required = [row for row in rows if row["required"]]
    score = sum(row["supported"] for row in required) / len(required) if required else 1.0
    if citation_contract_active and citation_details["invalid_citations"]:
        score = 0.0
    return round(score, 6), {
        "claims": rows,
        "citations": citation_details,
        "citation_contract_active": citation_contract_active,
    }


def _semantic_score(final_answer: str, rubric: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    requirements = list(rubric.get("requirements", []))
    if not requirements:
        return 1.0, {"requirements": []}
    total_weight = 0.0
    earned = 0.0
    rows = []
    for item in requirements:
        weight = float(item.get("weight", 1.0))
        score, matches = _group_score(final_answer, item.get("acceptable_terms", []))
        minimum = float(item.get("minimum_coverage", 1.0))
        passed = score >= minimum
        rows.append({"id": item.get("id"), "score": round(score, 6), "passed": passed, "matches": matches})
        total_weight += weight
        earned += weight * score
    return round(earned / max(total_weight, 1e-9), 6), {"requirements": rows}


def _process_score(trace: dict[str, Any], contract: dict[str, Any]) -> tuple[dict[str, float | None], dict[str, Any]]:
    calls = list(trace.get("tool_calls", []))
    fingerprints = [
        json.dumps([call.get("name"), call.get("arguments", {})], ensure_ascii=False, sort_keys=True) for call in calls
    ]
    duplicates = len(fingerprints) - len(set(fingerprints))
    successful = [call for call in calls if call.get("ok")]
    invalid = len([call for call in calls if call.get("error") in _DEFAULT_HARD_POLICY_ERRORS])
    tool_validity = 1.0 - invalid / max(1, len(calls))
    maximum = int(contract.get("max_reasonable_tool_calls", max(1, len(calls))))
    efficiency = max(0.0, 1.0 - 0.10 * duplicates - 0.12 * max(0, len(calls) - maximum))
    evidence_sources: set[str] = set()
    evidence_steps = 0
    for call in successful:
        returned = set(map(str, call.get("returned_source_ids", [])))
        new = returned - evidence_sources
        if new:
            evidence_steps += 1
            evidence_sources.update(new)
    target_gain_steps = int(contract.get("target_evidence_gain_steps", 0))
    evidence_gain = min(1.0, evidence_steps / target_gain_steps) if target_gain_steps > 0 else 1.0
    failed_indices = [index for index, call in enumerate(calls) if not call.get("ok")]
    recovery: float | None = None
    if contract.get("recovery_expected"):
        recovery = float(bool(failed_indices) and any(call.get("ok") for call in calls[min(failed_indices) + 1 :]))
    process = 0.45 * tool_validity + 0.30 * efficiency + 0.25 * evidence_gain
    if recovery is not None:
        process = 0.70 * process + 0.30 * recovery
    return (
        {
            "process": round(process, 6),
            "tool_validity": round(tool_validity, 6),
            "efficiency": round(efficiency, 6),
            "evidence_gain": round(evidence_gain, 6),
            "recovery": recovery,
        },
        {
            "tool_calls": len(calls),
            "successful_tool_calls": len(successful),
            "duplicate_calls": duplicates,
            "evidence_gain_steps": evidence_steps,
            "unique_evidence_sources": len(evidence_sources),
            "max_reasonable_tool_calls": maximum,
        },
    )


def evaluate_reward_v3(
    *,
    final_answer: str,
    trace: dict[str, Any],
    final_state: dict[str, Any],
    verifier: dict[str, Any],
) -> RewardV3Result:
    if verifier.get("schema_version") != "studyhub.reward-verifier.v3":
        raise ValueError("unsupported Reward v3 verifier schema")
    runtime_errors = sorted(set(map(str, trace.get("runtime_errors", []))))
    if runtime_errors:
        return RewardV3Result(
            status=INFRA_STATUS,
            total=0.0,
            strict_success=False,
            eligible_for_policy_update=False,
            hard_constraints=0.0,
            objective_end_state=0.0,
            semantic_rubric=0.0,
            grounding=0.0,
            process_quality=0.0,
            tool_validity=0.0,
            efficiency=0.0,
            evidence_gain=0.0,
            recovery=None,
            hard_gate_triggered=False,
            hard_gate_reasons=(),
            diagnostics={"infra_errors": runtime_errors},
        )

    calls = list(trace.get("tool_calls", []))
    objective = dict(verifier.get("objective", {}))
    objective["observed_successful_tool_calls"] = sum(bool(call.get("ok")) for call in calls)
    objective_score, objective_details = _objective_score(final_answer, final_state, objective)
    grounding, grounding_details = _claim_grounding(
        final_answer,
        trace,
        list(verifier.get("claims", [])),
    )
    semantic, semantic_details = _semantic_score(
        final_answer,
        dict(verifier.get("semantic_rubric", {})),
    )
    process_values, process_details = _process_score(
        trace,
        dict(verifier.get("process", {})),
    )

    constraints = dict(verifier.get("hard_constraints", {}))
    policy_errors = set(map(str, trace.get("policy_errors", [])))
    hard_policy_errors = set(map(str, constraints.get("hard_policy_errors", _DEFAULT_HARD_POLICY_ERRORS)))
    if constraints.get("allow_permission_denied"):
        hard_policy_errors.discard("permission_denied")
    hard_reasons = {f"policy:{error}" for error in policy_errors & hard_policy_errors}
    forbidden_tools = set(map(str, constraints.get("forbidden_tools", [])))
    hard_reasons.update(
        f"forbidden_tool:{call.get('name')}" for call in calls if str(call.get("name")) in forbidden_tools
    )
    forbidden_sources = set(map(str, constraints.get("forbidden_source_ids", [])))
    probed_sources = {
        str(call.get("arguments", {}).get("source_id"))
        for call in calls
        if call.get("arguments", {}).get("source_id") is not None
    }
    hard_reasons.update(f"forbidden_source:{source}" for source in forbidden_sources & probed_sources)
    invalid_citations = grounding_details["citations"]["invalid_citations"]
    if grounding_details["citation_contract_active"] or constraints.get("enforce_citation_contract"):
        hard_reasons.update(f"invalid_citation:{source}" for source in invalid_citations)
    for forbidden in constraints.get("forbidden_answer_strings", []):
        if _contains_phrase(final_answer, forbidden):
            hard_reasons.add("forbidden_answer_content")
    if not final_answer.strip():
        hard_reasons.add("empty_final_answer")
    maximum_calls = int(constraints.get("max_tool_calls", 0))
    if maximum_calls and len(calls) > maximum_calls:
        hard_reasons.add("tool_call_budget_exhausted")

    hard_gate = bool(hard_reasons)
    hard_score = 0.0 if hard_gate else 1.0
    weighted = 0.50 * objective_score + 0.25 * grounding + 0.15 * semantic + 0.10 * float(process_values["process"])
    total = max(-1.0, min(1.0, 2.0 * weighted - 1.0))
    if hard_gate:
        total = -1.0
    objective_threshold = float(verifier.get("thresholds", {}).get("objective", 0.99))
    grounding_threshold = float(verifier.get("thresholds", {}).get("grounding", 0.99))
    semantic_threshold = float(verifier.get("thresholds", {}).get("semantic", 0.75))
    strict = (
        not hard_gate
        and objective_score >= objective_threshold
        and grounding >= grounding_threshold
        and semantic >= semantic_threshold
    )
    return RewardV3Result(
        status=SCORED_STATUS,
        total=round(total, 6),
        strict_success=strict,
        eligible_for_policy_update=True,
        hard_constraints=hard_score,
        objective_end_state=objective_score,
        semantic_rubric=semantic,
        grounding=grounding,
        process_quality=float(process_values["process"]),
        tool_validity=float(process_values["tool_validity"]),
        efficiency=float(process_values["efficiency"]),
        evidence_gain=float(process_values["evidence_gain"]),
        recovery=process_values["recovery"],
        hard_gate_triggered=hard_gate,
        hard_gate_reasons=tuple(sorted(hard_reasons)),
        diagnostics={
            "reward_version": REWARD_VERSION,
            "objective": objective_details,
            "grounding": grounding_details,
            "semantic": semantic_details,
            "process": process_details,
            "path_agnostic": True,
            "gold_path_equality_used": False,
        },
    )
