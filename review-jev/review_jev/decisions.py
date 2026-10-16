from __future__ import annotations

import math

from .backends import BackendUnavailable, DecisionResult
from .policy import Policy
from .schemas import Finding, GuardScore, ModelAssessment
from .scoring import softmax


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
    if result.scores:
        return native_findings(result, policy)
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
    if result.scores:
        return min(
            max(score.decision_probabilities.values()) for score in result.scores
        ), "candidate_probability"
    if result.assessment is not None:
        raise BackendUnavailable("native_guard_probabilities_missing")
    # An uncertain rule must not be hidden by averaging confident unrelated rules.
    scores = validate_result(result, policy)
    return min(max(score, 1 - score) for score in scores.values()), "rule_probability"


def validate_guard_scores(result: DecisionResult, modality: str, image_ids: list[str]) -> None:
    validate_metadata(result)
    expected = (
        {("submission", "text_safety")}
        if modality == "text"
        else {
            (image_id, policy)
            for image_id in image_ids
            for policy in ("sexual", "dangerous", "violence")
        }
    )
    if not isinstance(result.scores, list) or len(result.scores) != len(expected) or result.answers:
        raise BackendUnavailable("incomplete_guard_scores")
    actual = set()
    for item in result.scores:
        if not isinstance(item, GuardScore):
            raise BackendUnavailable("invalid_guard_score")
        score = GuardScore.model_validate(item.model_dump())
        if (
            score.modality != modality
            or score.model != result.model
            or score.model_revision != result.model_revision
            or score.calibrated
        ):
            raise BackendUnavailable("guard_score_identity_mismatch")
        raw = softmax(score.log_scores, score.temperature)
        if any(not math.isclose(raw[key], score.probabilities[key], abs_tol=1e-5) for key in raw):
            raise BackendUnavailable("guard_score_probability_mismatch")
        actual.add((score.input_id, score.policy_id))
    if actual != expected:
        raise BackendUnavailable("incomplete_guard_scores")
    if modality == "text":
        if not isinstance(result.assessment, ModelAssessment):
            raise BackendUnavailable("native_guard_categories_missing")
        ModelAssessment.model_validate(result.assessment.model_dump())
    elif result.assessment is not None:
        raise BackendUnavailable("image_guard_returned_text_assessment")


def native_findings(result: DecisionResult, policy: Policy) -> list[Finding]:
    from .qwen_guard import guard_findings

    findings = []
    for score in result.scores:
        values = score.decision_probabilities
        thresholds = policy.guard_thresholds[score.policy_id]
        if score.modality == "text":
            findings.extend(guard_findings(result.assessment, policy, False))
            item = next(item for item in findings if item.rule_id == "guard_safety")
            item.risk_probability = values["Unsafe"]
            # Copyright-only signals never become automatic rejection through a safety label.
            copyright_only = set(result.assessment.categories) == {"Copyright Violation"}
            if values["Unsafe"] >= thresholds.reject and not copyright_only:
                item.outcome = "reject"
            elif (
                values["Unsafe"] >= thresholds.review
                or values["Controversial"] >= policy.controversial_threshold
            ):
                item.outcome = "review"
        else:
            probability = values["Yes"]
            findings.append(
                Finding(
                    rule_id=f"image_{score.policy_id}",
                    category="compliance",
                    scope="image",
                    input_id=score.input_id,
                    source="model",
                    outcome="reject"
                    if probability >= thresholds.reject
                    else ("review" if probability >= thresholds.review else "clear"),
                    risk_probability=probability,
                    reason=f"ShieldGemma 2 native image policy: {score.policy_id}.",
                )
            )
    if result.scores and result.scores[0].modality == "image":
        findings.extend(
            Finding(
                rule_id=rule.id,
                category=rule.category,
                source="model",
                scope="image",
                outcome="unavailable",
                reason="Image safety policies do not implement this custom StudyHub rule.",
            )
            for rule in policy.rules
            if rule.id not in {"sexual_content", "graphic_violence", "illegal_harm"}
        )
    return findings
