from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from .backends import AutoBackend, Backend, make_backend
from .cascade import run_cascade
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
        stages = self.backend.stages(images.media) if isinstance(self.backend, AutoBackend) else [
            ("single", self.backend, None)
        ]
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
        cascade = run_cascade(stages, self.policy, state, questions, images.media)
        backend = cascade.backend
        model = getattr(getattr(backend, "settings", None), "model", self.settings.model)
        model_revision = None
        assessment = None
        available = cascade.result is not None
        if available:
            result = cascade.result
            model = result.model
            model_revision = result.model_revision
            assessment = result.assessment
            findings.extend(cascade.findings)
            if assessment is not None:
                warnings.append(
                    "Qwen3Guard applies its native text policy, not the custom StudyHub policy. "
                    "Category mappings are approximate; no per-rule probabilities are available."
                )
                if request.content.images:
                    warnings.append("Text-only backend: submitted images were not evaluated.")
        if cascade.degraded:
            warnings.append(
                "Model unavailable or returned invalid results; human review is required."
            )
        if not available:
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
        status = "degraded" if cascade.degraded else "completed"
        rejected = [item.rule_id for item in findings if item.outcome == "reject"]
        review = [item.rule_id for item in findings if item.outcome == "review"]
        unavailable = [item.rule_id for item in findings if item.outcome == "unavailable"]
        if backend.demo:
            status = "demo"
            warnings.append("DEMO: probabilities are synthetic; no content was classified.")
            reasons = ["demo_mode"]
        elif cascade.human_review_reason:
            reasons = [cascade.human_review_reason, *review, *rejected]
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
            confidence=None if backend.demo else cascade.confidence,
            model_attempts=cascade.attempts,
            content_sha256=digest,
            image_sha256=images.sha256,
            findings=findings,
            copyright=assess_copyright(
                request, rights_checks, findings, available and not backend.demo
            ),
            warnings=warnings,
            usage=cascade.usage,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def close(self) -> None:
        self.backend.close()
