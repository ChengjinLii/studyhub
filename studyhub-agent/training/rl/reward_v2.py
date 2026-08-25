from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from training.rl.frozen_environment import ExecutionTrace, canonical_arguments


@dataclass(frozen=True, slots=True)
class RewardV2Result:
    total: float
    task_success: float
    evidence: float
    citation: float
    tool_quality: float
    efficiency: float
    violations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tokens(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]", value.casefold())


def _token_f1(candidate: str, expected: str) -> float:
    candidate_tokens = _tokens(candidate)
    expected_tokens = _tokens(expected)
    if not candidate_tokens or not expected_tokens:
        return float(candidate.strip().casefold() == expected.strip().casefold())
    candidate_counts = {token: candidate_tokens.count(token) for token in set(candidate_tokens)}
    expected_counts = {token: expected_tokens.count(token) for token in set(expected_tokens)}
    overlap = sum(min(candidate_counts.get(token, 0), count) for token, count in expected_counts.items())
    precision = overlap / len(candidate_tokens)
    recall = overlap / len(expected_tokens)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def _answer_score(final_answer: str, expected_answers: list[str]) -> float:
    if not final_answer.strip():
        return -1.0
    if not expected_answers:
        return 1.0
    normalized = final_answer.casefold()
    best = 0.0
    for expected in expected_answers:
        if expected.casefold() in normalized:
            best = 1.0
        else:
            best = max(best, _token_f1(final_answer, expected))
    return max(-1.0, min(1.0, 2 * best - 1))


def _function_score(trace: ExecutionTrace, verifier: dict[str, Any]) -> float:
    expected = verifier.get("expected_calls", [])
    actual = trace.tool_calls
    if not expected:
        return 1.0 if not actual else -1.0
    matches = 0
    for expected_call, actual_call in zip(expected, actual, strict=False):
        if expected_call.get("name") != actual_call.get("name"):
            continue
        if canonical_arguments(expected_call.get("arguments", {})) == canonical_arguments(
            actual_call.get("arguments", {})
        ):
            matches += 1
    denominator = max(len(expected), len(actual), 1)
    return (2 * matches / denominator) - 1


def _citation_score(final_answer: str, available: set[str], required: bool) -> tuple[float, list[str]]:
    cited = set(re.findall(r"\[(src-[a-f0-9]{12})\]", final_answer))
    invalid = cited - available
    violations = ["invalid_citation"] if invalid else []
    if not cited:
        if required:
            violations.append("missing_citation")
            return -1.0, violations
        return 1.0, violations
    return (2 * len(cited - invalid) / len(cited)) - 1, violations


def evaluate_reward_v2(
    *,
    final_answer: str,
    trace: ExecutionTrace,
    verifier: dict[str, Any],
    max_tool_calls: int,
) -> RewardV2Result:
    violations = []
    family = verifier["family"]
    answer_score = _answer_score(final_answer, verifier.get("expected_answers", []))
    if family == "function_calling":
        task_success = _function_score(trace, verifier)
        evidence = 1.0
        citation = 1.0
    else:
        task_success = answer_score
        gold_sources = set(verifier.get("gold_source_ids", []))
        if gold_sources:
            evidence = (2 * len(trace.read_source_ids & gold_sources) / len(gold_sources)) - 1
        else:
            evidence = 1.0
        citation, citation_violations = _citation_score(
            final_answer,
            trace.read_source_ids,
            bool(verifier.get("citations_required", False)),
        )
        violations.extend(citation_violations)
    total_calls = len(trace.tool_calls)
    valid_calls = max(0, total_calls - trace.invalid_tool_calls)
    if total_calls:
        tool_quality = (2 * valid_calls / total_calls) - 1
    else:
        tool_quality = -1.0
        violations.append("no_tool_call")
    if trace.invalid_tool_calls:
        violations.append("invalid_tool_call")
    if not final_answer.strip():
        violations.append("empty_final_answer")
    efficiency = 1.0 - min(2.0, 2 * total_calls / max(1, max_tool_calls))
    weighted = 0.40 * task_success + 0.25 * evidence + 0.15 * citation + 0.15 * tool_quality + 0.05 * efficiency
    penalty = min(0.75, 0.15 * len(set(violations)))
    total = max(-1.0, min(1.0, weighted - penalty))
    return RewardV2Result(
        total=round(total, 6),
        task_success=round(task_success, 6),
        evidence=round(evidence, 6),
        citation=round(citation, 6),
        tool_quality=round(tool_quality, 6),
        efficiency=round(efficiency, 6),
        violations=tuple(dict.fromkeys(violations)),
    )
