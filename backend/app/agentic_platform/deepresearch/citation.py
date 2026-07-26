from __future__ import annotations

from .state import (
    CitationMetrics,
    CitationValidationResult,
    Claim,
    ClaimSupportStatus,
    EvidenceRecord,
    ResearchReport,
)


class CitationVerifier:
    """Rejects report claims that lack a real supporting evidence link."""

    def validate(
        self,
        report: ResearchReport,
        *,
        claims: list[Claim],
        evidence: list[EvidenceRecord],
    ) -> CitationValidationResult:
        claim_by_id = {claim.claim_id: claim for claim in claims}
        evidence_by_id = {record.evidence_id: record for record in evidence}
        cited_claim_ids: set[str] = set()
        invalid_citations = 0
        cited_by_claim: dict[str, set[str]] = {}
        for section in report.sections:
            for citation in section.citations:
                cited_claim_ids.add(citation.claim_id)
                cited_by_claim.setdefault(citation.claim_id, set()).add(citation.evidence_id)
                claim = claim_by_id.get(citation.claim_id)
                record = evidence_by_id.get(citation.evidence_id)
                if claim is None or record is None:
                    invalid_citations += 1
                    continue
                explicit_support = citation.claim_id in record.supports_claim_ids
                inferred_support = citation.evidence_id in claim.evidence_ids and claim.status == ClaimSupportStatus.SUPPORTED
                if not explicit_support and not inferred_support:
                    invalid_citations += 1

        unsupported: list[str] = []
        for section in report.sections:
            for claim_id in section.claim_ids:
                claim = claim_by_id.get(claim_id)
                if claim is None:
                    unsupported.append(claim_id)
                    continue
                if claim.status != ClaimSupportStatus.SUPPORTED or not cited_by_claim.get(claim_id):
                    unsupported.append(claim_id)
        unsupported = list(dict.fromkeys(unsupported))
        supported_claim_count = sum(
            1
            for claim_id in cited_claim_ids
            if claim_by_id.get(claim_id) is not None and claim_by_id[claim_id].status == ClaimSupportStatus.SUPPORTED
        )
        metrics = CitationMetrics(
            cited_claim_count=len(cited_claim_ids),
            supported_claim_count=supported_claim_count,
            unsupported_claim_ids=unsupported,
            invalid_citation_count=invalid_citations,
        )
        passed = not unsupported and invalid_citations == 0
        return CitationValidationResult(
            passed=passed,
            metrics=metrics,
            summary="All report claims have valid support." if passed else "Report contains unsupported or invalidly cited claims.",
        )
