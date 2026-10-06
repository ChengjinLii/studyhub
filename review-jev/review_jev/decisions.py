from __future__ import annotations

import math

from .backends import BackendUnavailable, DecisionResult
from .policy import Policy
from .schemas import Finding, ModelAssessment


def validate_metadata(result: DecisionResult) -> None:
    if not isinstance(result, DecisionResult):
        raise BackendUnavailable("invalid_decision_result")
    if not isinstance(result.model, str) or not result.model or len(result.model) > 256:
        raise BackendUnavailable("invalid_model_identity")
    if result.model_revision is not None and (
        not isinstance(result.model_revision, str) or not 1 <= len(result.model_revision) <= 256
    ):
        raise BackendUnavailable("invalid_model_revision")
    if not isinstance(result.usage, dict):
        raise BackendUnavailable("invalid_usage")
    for value in result.usage.values():
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100_000_000:
            raise BackendUnavailable("invalid_usage")
    if result.confidence is not None and (
        isinstance(result.confidence, bool)
        or not isinstance(result.confidence, (int, float))
        or not math.isfinite(result.confidence)
        or not 0 <= result.confidence <= 1
    ):
        raise BackendUnavailable("invalid_confidence")


def validate_result(result: DecisionResult, policy: Policy) -> dict[str, float]:
    validate_metadata(result)
    if not isinstance(result.answers, dict) or set(result.answers) != {
        rule.id for rule in policy.rules
    }:
        raise BackendUnavailable("incomplete_backend_answers")
    scores = {}
    for rule in policy.rules:
        answer = result.answers[rule.id]
        if not isinstance(answer, dict) or answer.get("type") != "noul":
            raise BackendUnavailable("invalid_answer_type")
        value = answer.get("noul")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise BackendUnavailable("invalid_probability")
        scores[rule.id] = float(value) if rule.positive_means == "risk" else 1 - float(value)
    return scores


def model_findings(
    result: DecisionResult, policy: Policy, demo: bool, has_images: bool
) -> list[Finding]:
    validate_metadata(result)
    if result.assessment is not None:
        from .qwen_guard import guard_findings

        if demo or result.answers or not isinstance(result.assessment, ModelAssessment):
            raise BackendUnavailable("invalid_classification_result")
        return guard_findings(result.assessment, policy, has_images)
    scores = validate_result(result, policy)
    findings = []
    for rule in policy.rules:
        score = scores[rule.id]
        outcome = "clear"
        if rule.reject_threshold is not None and score >= rule.reject_threshold:
            outcome = "reject"
        elif score >= rule.review_threshold:
            outcome = "review"
        findings.append(
            Finding(
                rule_id=rule.id,
                category=rule.category,
                source="model",
                outcome=outcome,
                risk_probability=round(score, 6),
                reason="DEMO synthetic score; this rule was not evaluated."
                if demo
                else (
                    rule.reason
                    if outcome != "clear"
                    else "No model risk signal above threshold; "
                    "not proof of compliance or permission."
                ),
            )
        )
    return findings


def result_confidence(result: DecisionResult, policy: Policy) -> tuple[float | None, str]:
    if result.assessment is not None:
        return result.confidence, "native_label_probability"
    # An uncertain rule must not be hidden by averaging confident unrelated rules.
    scores = validate_result(result, policy)
    return min(max(score, 1 - score) for score in scores.values()), "rule_probability"
