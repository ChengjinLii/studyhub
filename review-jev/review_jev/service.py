from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from typing import Any

from .backends import AutoBackend, Backend, BackendUnavailable, DecisionResult, make_backend
from .config import Settings
from .copyright import assess_copyright, check_rights, text_parts
from .media import prepare_images
from .policy import Policy, load_policy
from .schemas import Finding, ReviewRequest, ReviewResponse


def escape_evidence(value: Any) -> Any:
    if isinstance(value, str):
        # Prevent user-controlled strings becoming media placeholders or chat-template tokens.
        return (
            value.replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("QEV_PREFIX_MARK", "QEV_PREFIX[underscore]MARK")
        )
    if isinstance(value, dict):
        return {key: escape_evidence(item) for key, item in value.items()}
    if isinstance(value, list):
        return [escape_evidence(item) for item in value]
    return value


def build_decision_request(request: ReviewRequest, policy: Policy) -> tuple[dict, dict]:
    state = {
        "review_task": policy.instructions,
        "untrusted_submission": escape_evidence(text_parts(request)),
        "unverified_context": escape_evidence(request.context.model_dump()),
        "unverified_rights_declaration": escape_evidence(request.rights.model_dump()),
        "images": [
            {"id": image.id, "content": f"<image:{index}>"}
            for index, image in enumerate(request.content.images, 1)
        ],
    }
    questions = {
        rule.id: {
            "type": "noul",
            "instructions": policy.instructions + "\n\n" + rule.question,
            "criteria": {
                "true": "Yes, based on the submitted content and pixels.",
                "false": "No, based on the submitted content and pixels.",
            },
        }
        for rule in policy.rules
    }
    return state, questions


def validate_metadata(result: DecisionResult) -> None:
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


def model_findings(result: DecisionResult, policy: Policy, demo: bool, has_images: bool):
    if result.assessment is not None:
        from .qwen_guard import guard_findings
        from .schemas import ModelAssessment

        validate_metadata(result)
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


class ReviewService:
    def __init__(
        self,
        settings: Settings | None = None,
        backend: Backend | None = None,
        policy: Policy | None = None,
    ):
        self.settings = settings or Settings.from_env()
        self.backend = backend or make_backend(self.settings)
        self.policy = policy or load_policy(self.settings.policy_path)

    def review(self, request: ReviewRequest) -> ReviewResponse:
        started = time.perf_counter()
        images = prepare_images(request.content)
        backend = (
            self.backend.select(images.media)
            if isinstance(self.backend, AutoBackend)
            else self.backend
        )
        content = {**text_parts(request), "images": images.sha256}
        digest = hashlib.sha256(
            json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        rights_checks = check_rights(request, images.sha256)
        findings = list(rights_checks.findings)
        warnings = ["Thresholds are development defaults, not calibrated for StudyHub."]
        state, questions = build_decision_request(request, self.policy)
        usage: dict[str, int] = {}
        model = getattr(getattr(backend, "settings", None), "model", self.settings.model)
        model_revision = None
        assessment = None
        available = False
        try:
            result = backend.decide(state, questions, images.media)
            evaluated = model_findings(
                result, self.policy, backend.demo, bool(request.content.images)
            )
            model, available = result.model, True
            model_revision = result.model_revision
            assessment = result.assessment
            usage = {
                key: result.usage[key]
                for key in ("input_tokens", "output_tokens")
                if key in result.usage
            }
            findings.extend(evaluated)
            if assessment is not None:
                warnings.append(
                    "Qwen3Guard applies its native text policy, not the custom StudyHub policy. "
                    "Category mappings are approximate; no per-rule probabilities are available."
                )
                if request.content.images:
                    warnings.append("Text-only backend: submitted images were not evaluated.")
        except BackendUnavailable:
            warnings.append(
                "Model unavailable or returned invalid results; human review is required."
            )
            findings.extend(
                Finding(
                    rule_id=rule.id,
                    category=rule.category,
                    source="model",
                    outcome="unavailable",
                    reason="This check could not be completed; do not infer a safe result.",
                )
                for rule in self.policy.rules
            )

        decision, reasons = "manual_review", []
        status = "completed" if available else "degraded"
        rejected = [item.rule_id for item in findings if item.outcome == "reject"]
        review = [item.rule_id for item in findings if item.outcome == "review"]
        unavailable = [item.rule_id for item in findings if item.outcome == "unavailable"]
        if backend.demo:
            status = "demo"
            warnings.append("DEMO: probabilities are synthetic; no content was classified.")
            reasons = ["demo_mode"]
        elif not available:
            reasons = ["model_unavailable", *review]
        elif unavailable or assessment is not None:
            status = "partial"
            reasons = [
                "model_coverage_incomplete" if unavailable else "native_policy_not_studyhub",
                *unavailable,
                *review,
            ]
        elif rejected:
            decision = "reject" if self.settings.allow_auto_reject else "manual_review"
            reasons = rejected
            if not self.settings.allow_auto_reject:
                reasons.append("automatic_rejection_disabled")
        elif review:
            reasons = review
        elif not self.settings.allow_auto_approve:
            reasons = ["automatic_approval_disabled"]
        else:
            decision, reasons = "approve", ["no_review_signals_detected"]

        return ReviewResponse(
            request_id=request.request_id or f"req-{uuid.uuid4().hex}",
            review_id=f"review-{uuid.uuid4().hex}",
            status=status,
            decision=decision,
            decision_reasons=reasons,
            policy_version=self.policy.version,
            policy_sha256=self.policy.sha256,
            model=model,
            model_revision=model_revision,
            backend=backend.name,
            model_assessment=assessment,
            content_sha256=digest,
            image_sha256=images.sha256,
            findings=findings,
            copyright=assess_copyright(
                request, rights_checks, findings, available and not backend.demo
            ),
            warnings=warnings,
            usage=usage,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def close(self) -> None:
        self.backend.close()
