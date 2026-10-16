from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

from .backends import Backend, DecisionResult
from .decisions import model_findings, result_confidence, validate_guard_scores, validate_metadata
from .policy import Policy
from .schemas import Coverage, Finding, GuardScore, ModelAttempt
from .scoring import Calibration


@dataclass
class RoutingResult:
    results: list[DecisionResult] = field(default_factory=list)
    scores: list[GuardScore] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    attempts: list[ModelAttempt] = field(default_factory=list)
    coverage: list[Coverage] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    review_reasons: list[str] = field(default_factory=list)
    degraded: bool = False


def run_branches(
    branches: list[tuple[str, Backend, float | None]],
    policy: Policy,
    state: dict,
    questions: dict,
    media: list[dict],
    calibration: Calibration,
) -> RoutingResult:
    routed = RoutingResult()
    for modality, backend, threshold in branches:
        started = time.perf_counter()
        image_ids = state.get("image_ids", [])
        input_ids = image_ids if modality == "image" else ["submission"]
        try:
            # No captions or OCR are smuggled into ShieldGemma's policy prompt.
            branch_state = {"image_ids": image_ids} if modality == "image" else state
            result = backend.decide(branch_state, questions, media if modality != "text" else [])
            validate_metadata(result)
            if modality in {"text", "image"}:
                validate_guard_scores(result, modality, image_ids)
                result = replace(result, scores=[calibration.apply(s) for s in result.scores])
            findings = model_findings(result, policy, backend.demo, bool(media))
            confidence, method = result_confidence(result, policy)
            reason = None
            if (
                not backend.demo
                and threshold is not None
                and (confidence is None or confidence < threshold)
            ):
                reason = "low_confidence"
            if result.assessment:
                label = max(
                    result.scores[0].decision_probabilities,
                    key=(result.scores[0].decision_probabilities.get),
                )
                if label != result.assessment.safety:
                    reason = "native_label_disagreement"
                elif label == "Controversial":
                    reason = "native_controversial"
            routed.results.append(result)
            routed.scores.extend(result.scores)
            routed.findings.extend(findings)
            for key, value in result.usage.items():
                routed.usage[key] = routed.usage.get(key, 0) + value
            if reason:
                routed.review_reasons.append(reason)
            routed.attempts.append(
                ModelAttempt(
                    tier=modality,
                    input_ids=input_ids,
                    model=result.model,
                    model_revision=result.model_revision,
                    backend=backend.name,
                    outcome="demo" if backend.demo else ("manual_review" if reason else "accepted"),
                    confidence=None if backend.demo else confidence,
                    confidence_threshold=threshold,
                    confidence_method=None if backend.demo else method,
                    review_reason=reason,
                    findings=findings,
                    model_assessment=result.assessment,
                    usage=result.usage,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                )
            )
            if modality != "single":
                routed.coverage.append(
                    Coverage(modality=modality, input_ids=input_ids, status="completed")
                )
        except Exception:
            # Keep successful evidence from other branches; never serialize exception text.
            routed.degraded = True
            routed.review_reasons.append(f"{modality}_backend_unavailable")
            routed.attempts.append(
                ModelAttempt(
                    tier=modality,
                    input_ids=input_ids,
                    model=getattr(getattr(backend, "settings", None), "model", backend.name),
                    backend=backend.name,
                    outcome="unavailable",
                    confidence_threshold=threshold,
                    review_reason="backend_unavailable",
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                )
            )
            if modality != "single":
                routed.coverage.append(
                    Coverage(
                        modality=modality,
                        input_ids=input_ids,
                        status="unavailable",
                        reason="backend_unavailable",
                    )
                )
    return routed
