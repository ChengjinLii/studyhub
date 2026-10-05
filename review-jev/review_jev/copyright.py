from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from .schemas import CopyrightAssessment, Finding, ReviewRequest

KNOWN_LICENSES = {
    "CC0-1.0",
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
    "CC-BY-NC-4.0",
    "CC-BY-ND-4.0",
    "CC-BY-NC-SA-4.0",
    "CC-BY-NC-ND-4.0",
    "MIT",
    "Apache-2.0",
}


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def text_digest(text: str) -> str:
    return hashlib.sha256(normalized_text(text).encode("utf-8")).hexdigest()


def text_parts(request: ReviewRequest) -> dict[str, str]:
    return {
        key: value
        for key in ("title", "description", "text", "customPreviewText")
        if (value := getattr(request.content, key))
    }


def _shingles(text: str, size: int = 8) -> set[str]:
    return {text[i : i + size] for i in range(len(text) - size + 1)}


@dataclass(frozen=True)
class RightsChecks:
    findings: list[Finding]
    matched_ids: list[str]
    declaration_complete: bool


def check_rights(request: ReviewRequest, image_hashes: dict[str, str]) -> RightsChecks:
    findings: list[Finding] = []
    rights = request.rights

    def review(
        rule_id: str, reason: str, evidence: list[str] | None = None, source: str = "declaration"
    ) -> None:
        findings.append(
            Finding(
                rule_id=rule_id,
                category="copyright",
                source=source,
                outcome="review",
                reason=reason,
                evidence=evidence or [],
            )
        )

    declaration_required = request.context.kind in {"material", "experience"}
    complete = rights.basis != "unknown" and rights.attested
    if declaration_required and not complete:
        review(
            "rights_declaration_missing", "Sharing-rights declaration is missing or not attested."
        )
    if complete and rights.basis == "original" and not rights.copyrightOwner:
        review(
            "original_author_missing", "Identify the declared author; ownership is not verified."
        )
    if complete and rights.basis == "authorized":
        if not rights.copyrightOwner or not rights.authorization_note:
            review("authorization_evidence_missing", "Request owner and authorization details.")
    if complete and rights.basis == "public_domain" and not rights.source_url:
        review("public_domain_source_missing", "Request provenance for the public-domain claim.")
    if complete and rights.basis == "open_license":
        license_id = rights.license
        if license_id not in KNOWN_LICENSES or not rights.source_url:
            review("license_evidence_missing", "Request a recognized license and original source.")
        if license_id.startswith("CC-BY") and not rights.attribution:
            review("attribution_missing", "Check attribution required by the declared license.")
        if "-NC-" in license_id and request.context.publication_intent == "PAID":
            review("commercial_license_conflict", "Paid publication may conflict with NC terms.")
        if "-ND-" in license_id and rights.modified:
            review("derivative_license_conflict", "Modified content may conflict with ND terms.")

    parts = {key: normalized_text(value) for key, value in text_parts(request).items()}
    part_shingles = {key: _shingles(value) for key, value in parts.items() if len(value) >= 160}
    matched: list[str] = []
    for reference in request.references:
        evidence = []
        if reference.image_sha256:
            evidence += [
                f"image:{key}:sha256_match"
                for key, digest in image_hashes.items()
                if digest == reference.image_sha256
            ]
        candidate = normalized_text(reference.text)
        if len(candidate) >= 100:
            for key, value in parts.items():
                if len(value) >= 100 and (candidate in value or value in candidate):
                    evidence.append(f"text:{key}:contained_match")
            if len(candidate) >= 160:
                ref_shingles = _shingles(candidate)
                for key, shingles in part_shingles.items():
                    overlap = len(shingles & ref_shingles) / max(1, len(shingles))
                    if overlap >= 0.85 and not any(f"text:{key}:" in item for item in evidence):
                        evidence.append(f"text:{key}:shingle_overlap={overlap:.3f}")
        if evidence:
            matched.append(reference.id)
            review(
                "reference_match",
                "Similarity to a supplied reference requires rights verification; "
                "matching does not establish infringement.",
                [f"reference:{reference.id}", *evidence],
                "reference",
            )
    return RightsChecks(findings, matched, complete)


def assess_copyright(
    request: ReviewRequest, checks: RightsChecks, findings: list[Finding], model_available: bool
) -> CopyrightAssessment:
    copyright_findings = [
        finding
        for finding in findings
        if finding.category == "copyright" and (model_available or finding.source != "model")
    ]
    if any(finding.outcome == "review" for finding in copyright_findings):
        status = "needs_review"
    elif (
        not model_available
        or not checks.declaration_complete
        or not copyright_findings
        or any(finding.outcome == "unavailable" for finding in copyright_findings)
    ):
        status = "undetermined"
    else:
        status = "no_obvious_risk"
    return CopyrightAssessment(
        status=status,
        reference_search_performed=bool(request.references),
        matched_reference_ids=checks.matched_ids,
        limitations=[
            "Risk screening only; no legal ownership or infringement determination.",
            "Declarations, sources, and authorization notes are unverified user claims.",
            "Only caller-supplied references were compared; "
            "no external rights database or web search.",
            "Short quotations, transformed images, and translations "
            "need human/contextual assessment.",
        ],
    )
