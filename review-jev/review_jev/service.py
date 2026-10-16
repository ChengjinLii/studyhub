from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from .backends import AutoBackend, Backend, make_backend
from .config import Settings
from .copyright import assess_copyright, check_rights, text_parts
from .media import prepare_images
from .ocr import TesseractOCR
from .policy import Policy, load_policy
from .routing import run_branches
from .schemas import Coverage, Finding, ReviewRequest, ReviewResponse
from .scoring import Calibration


def escape_evidence(value: Any) -> Any:
    if isinstance(value, str):
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
        "image_ids": [image.id for image in request.content.images],
        "images": [
            {"id": image.id, "content": f"<image:{index}>"}
            for index, image in enumerate(request.content.images, 1)
        ],
    }
    questions = {
        rule.id: {
            "type": "noul",
            "instructions": policy.instructions + "\n\n" + rule.question,
            "criteria": {"true": "Risk detected.", "false": "No risk detected."},
        }
        for rule in policy.rules
    }
    return state, questions


class ReviewService:
    def __init__(
        self,
        settings: Settings | None = None,
        backend: Backend | AutoBackend | None = None,
        policy: Policy | None = None,
        ocr: TesseractOCR | None = None,
    ):
        self.settings = settings or Settings.from_env()
        self.backend = backend or make_backend(self.settings)
        self.policy = policy or load_policy(self.settings.policy_path)
        self.calibration = Calibration.load(self.settings.calibration_path)
        self.ocr = ocr or TesseractOCR(self.settings)

    def review(self, request: ReviewRequest) -> ReviewResponse:
        started = time.perf_counter()
        images = prepare_images(request.content)
        state, questions = build_decision_request(request, self.policy)
        ocr_attempts, ocr_coverage = [], []
        native = isinstance(self.backend, AutoBackend) or self.backend.name in {
            "qwen3guard",
            "shieldgemma2",
        }
        if native:
            for image, media in zip(request.content.images, images.media):
                result = self.ocr.extract(image.id, media["data"])
                ocr_attempts.append(result.attempt)
                if result.text:
                    state["untrusted_submission"][f"ocr:{image.id}"] = escape_evidence(result.text)
                complete = result.attempt.status in {"completed", "empty"}
                ocr_coverage.append(
                    Coverage(
                        modality="ocr",
                        input_ids=[image.id],
                        status="completed" if complete else "unavailable",
                        reason=None if complete else f"ocr_{result.attempt.status}",
                    )
                )
        has_text = bool(state["untrusted_submission"])
        if isinstance(self.backend, AutoBackend):
            branches = self.backend.branches(has_text, images.media)
        elif self.backend.name in {"qwen3guard", "shieldgemma2"}:
            modality = "text" if self.backend.name == "qwen3guard" else "image"
            threshold = getattr(self.settings, f"{modality}_confidence_threshold")
            branches = [(modality, self.backend, threshold)]
        else:
            branches = [("single", self.backend, None)]
        routed = run_branches(
            branches, self.policy, state, questions, images.media, self.calibration
        )
        coverage = [*ocr_coverage, *routed.coverage]
        if native:
            requested = {modality for modality, _, _ in branches}
            for modality, exists, ids in (
                ("text", has_text, ["submission"]),
                ("image", bool(images.media), state["image_ids"]),
            ):
                if modality not in requested:
                    coverage.append(
                        Coverage(
                            modality=modality,
                            input_ids=ids if exists else [],
                            status="unavailable" if exists else "not_requested",
                            reason="fixed_backend_does_not_cover_modality" if exists else None,
                        )
                    )

        content = {**text_parts(request), "images": images.sha256}
        digest = hashlib.sha256(
            json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        rights_checks = check_rights(request, images.sha256)
        findings = [*rights_checks.findings, *routed.findings]
        if not routed.results:
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
        missing = [item for item in coverage if item.status == "unavailable"]
        reasons = list(
            dict.fromkeys(
                routed.review_reasons
                + [item.reason or "model_coverage_incomplete" for item in missing]
            )
        )
        rejected = [item.rule_id for item in findings if item.outcome == "reject"]
        review = [item.rule_id for item in findings if item.outcome == "review"]
        unavailable = [item.rule_id for item in findings if item.outcome == "unavailable"]
        decision = "manual_review"
        status = "degraded" if routed.degraded else "completed"
        warnings = []
        if routed.scores and not all(score.calibrated for score in routed.scores):
            warnings.append("Raw candidate probabilities have not been calibrated for StudyHub.")
        if self.backend.demo:
            status, reasons = "demo", ["demo_mode"]
            warnings.append("DEMO: probabilities are synthetic; no content was classified.")
        elif reasons:
            if not routed.degraded:
                status = "partial"
            reasons += [*review, *rejected]
        elif rejected:
            decision = "reject" if self.settings.allow_auto_reject else "manual_review"
            reasons = rejected
            if not self.settings.allow_auto_reject:
                reasons.append("automatic_rejection_disabled")
        elif routed.scores:
            status = "partial"
            reasons = ["native_policy_not_studyhub", *unavailable, *review]
        elif unavailable:
            status, reasons = "partial", ["model_coverage_incomplete", *unavailable, *review]
        elif review:
            reasons = review
        elif not self.settings.allow_auto_approve:
            reasons = ["automatic_approval_disabled"]
        else:
            decision, reasons = "approve", ["no_review_signals_detected"]
        if unavailable and status == "completed":
            status = "partial"
        models = list(dict.fromkeys(result.model for result in routed.results))
        assessment = next((r.assessment for r in routed.results if r.assessment), None)
        single = routed.results[0] if len(routed.results) == 1 else None
        return ReviewResponse(
            request_id=request.request_id or f"req-{uuid.uuid4().hex}",
            review_id=f"review-{uuid.uuid4().hex}",
            status=status,
            decision=decision,
            decision_reasons=list(dict.fromkeys(reasons)),
            policy_version=self.policy.version,
            policy_sha256=self.policy.sha256,
            model=" + ".join(models) if models else self.settings.model,
            model_revision=single.model_revision if single else None,
            backend=self.backend.name,
            model_assessment=assessment,
            confidence=(routed.attempts[0].confidence if len(routed.attempts) == 1 else None),
            model_attempts=routed.attempts,
            guard_scores=routed.scores,
            coverage=coverage,
            ocr_attempts=ocr_attempts,
            calibrated_for_studyhub=(
                bool(routed.scores) and all(s.calibrated for s in routed.scores)
            ),
            content_sha256=digest,
            image_sha256=images.sha256,
            findings=findings,
            copyright=assess_copyright(
                request, rights_checks, findings, bool(routed.results) and not self.backend.demo
            ),
            warnings=warnings,
            usage=routed.usage,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    def close(self) -> None:
        self.backend.close()
