from __future__ import annotations

import time
from dataclasses import dataclass, field

from .backends import Backend, BackendUnavailable, DecisionResult
from .decisions import model_findings, result_confidence
from .policy import Policy
from .schemas import Finding, ModelAttempt


@dataclass
class CascadeResult:
    backend: Backend
    result: DecisionResult | None = None
    findings: list[Finding] = field(default_factory=list)
    attempts: list[ModelAttempt] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    confidence: float | None = None
    human_review_reason: str | None = None
    degraded: bool = False


def run_cascade(
    stages: list[tuple[str, Backend, float | None]],
    policy: Policy,
    state: dict,
    questions: dict,
    media: list[dict],
) -> CascadeResult:
    outcome = CascadeResult(backend=stages[0][1])
    for index, (tier, backend, threshold) in enumerate(stages):
        started = time.perf_counter()
        has_next = index + 1 < len(stages)
        model = getattr(getattr(backend, "settings", None), "model", backend.name)
        revision = getattr(getattr(backend, "settings", None), "model_revision", None)
        try:
            # Each stage independently reads the original evidence, not earlier model instructions.
            result = backend.decide(state, questions, media)
            findings = model_findings(result, policy, backend.demo, bool(media))
            confidence, method = result_confidence(result, policy)
        except BackendUnavailable:
            outcome.attempts.append(
                ModelAttempt(
                    tier=tier,
                    model=model,
                    model_revision=revision,
                    backend=backend.name,
                    outcome="escalated" if has_next else "unavailable",
                    confidence_threshold=threshold,
                    escalation_reason="backend_unavailable",
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
                )
            )
            if has_next:
                continue
            outcome.human_review_reason = "model_unavailable"
            outcome.degraded = True
            if outcome.result is None:
                outcome.backend = backend
            break

        usage = {
            key: result.usage[key]
            for key in ("input_tokens", "output_tokens")
            if key in result.usage
        }
        for key, value in usage.items():
            outcome.usage[key] = outcome.usage.get(key, 0) + value
        outcome.backend, outcome.result, outcome.findings = backend, result, findings
        outcome.confidence = confidence
        reason = None
        if threshold is not None and not backend.demo:
            if confidence is None:
                reason = "confidence_missing"
            elif confidence < threshold:
                reason = "low_confidence"
            elif result.assessment is not None and result.assessment.safety == "Controversial":
                reason = "native_controversial"
        attempt_outcome = "accepted"
        if backend.demo:
            attempt_outcome = "demo"
        elif reason:
            attempt_outcome = "escalated" if has_next else "manual_review"
        outcome.attempts.append(
            ModelAttempt(
                tier=tier,
                model=result.model,
                model_revision=result.model_revision,
                backend=backend.name,
                outcome=attempt_outcome,
                confidence=None if backend.demo else confidence,
                confidence_threshold=threshold,
                confidence_method=None if backend.demo else method,
                escalation_reason=reason,
                findings=findings,
                model_assessment=result.assessment,
                usage=usage,
                elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        )
        if reason is None or backend.demo:
            break
        if not has_next:
            outcome.human_review_reason = "low_confidence_after_escalation"
    return outcome
