from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from app.agentic_platform.domain.hashing import canonical_hash

from .state import Claim, ClaimSupportStatus, EvidenceRecord, ResearchConflict, ResearchStateDelta


def extract_claims_from_evidence(
    evidence: Iterable[EvidenceRecord],
    *,
    claim_candidates: Iterable[str] = (),
) -> list[Claim]:
    """Build bounded draft claims from explicit candidates or source excerpts."""

    records = list(evidence)
    candidates = [" ".join(value.split()).strip() for value in claim_candidates]
    candidates = [value for value in candidates if value]
    if not candidates:
        candidates = [_sentence_candidate(record.excerpt) for record in records]
    claims: list[Claim] = []
    for statement in candidates:
        if not statement:
            continue
        claim_id = f"claim_{canonical_hash(statement)[:24]}"
        if any(claim.claim_id == claim_id for claim in claims):
            continue
        related = [record.evidence_id for record in records if _shares_terms(statement, record.excerpt)]
        claims.append(
            Claim(
                claim_id=claim_id,
                statement=statement[:2_000],
                status=ClaimSupportStatus.DRAFT,
                evidence_ids=related,
                confidence=0.0,
            )
        )
    return claims


def reconcile_claims(claims: Iterable[Claim], evidence: Iterable[EvidenceRecord]) -> ResearchStateDelta:
    """Create claim/evidence updates and conflicts without deleting source records."""

    evidence_records = list(evidence)
    evidence_updates: dict[str, EvidenceRecord] = {}
    claim_updates: dict[str, Claim] = {}
    conflicts: list[ResearchConflict] = []
    for claim in claims:
        supporting = [record.evidence_id for record in evidence_records if claim.claim_id in record.supports_claim_ids]
        contradicting = [record.evidence_id for record in evidence_records if claim.claim_id in record.contradicts_claim_ids]
        inferred = [record.evidence_id for record in evidence_records if _shares_terms(claim.statement, record.excerpt)]
        if not supporting and not contradicting:
            supporting = inferred
        evidence_ids = list(dict.fromkeys([*supporting, *contradicting, *claim.evidence_ids]))
        if supporting and contradicting:
            status = ClaimSupportStatus.CONFLICTED
            confidence = min(0.5, _confidence_for(supporting, evidence_records))
            conflict_id = f"conflict_{canonical_hash({'claim': claim.claim_id, 'supports': supporting, 'contradicts': contradicting})[:24]}"
            conflicts.append(
                ResearchConflict(
                    conflict_id=conflict_id,
                    claim_id=claim.claim_id,
                    supporting_evidence_ids=supporting,
                    contradicting_evidence_ids=contradicting,
                    summary="Independent evidence supports incompatible interpretations of this claim.",
                )
            )
        elif supporting:
            status = ClaimSupportStatus.SUPPORTED
            confidence = _confidence_for(supporting, evidence_records)
        else:
            status = ClaimSupportStatus.UNSUPPORTED
            confidence = 0.0
        claim_updates[claim.claim_id] = claim.model_copy(
            update={"status": status, "evidence_ids": evidence_ids, "confidence": confidence}
        )
        for record in evidence_records:
            supports = list(record.supports_claim_ids)
            contradicts = list(record.contradicts_claim_ids)
            if record.evidence_id in supporting and claim.claim_id not in supports:
                supports.append(claim.claim_id)
            if record.evidence_id in contradicting and claim.claim_id not in contradicts:
                contradicts.append(claim.claim_id)
            if supports != record.supports_claim_ids or contradicts != record.contradicts_claim_ids:
                evidence_updates[record.evidence_id] = record.model_copy(
                    update={"supports_claim_ids": supports, "contradicts_claim_ids": contradicts}
                )
    return ResearchStateDelta(claim_updates=claim_updates, evidence_updates=evidence_updates, conflicts_to_add=conflicts)


def unresolved_claim_questions(claims: Iterable[Claim]) -> list[str]:
    questions: list[str] = []
    for claim in claims:
        if claim.status == ClaimSupportStatus.UNSUPPORTED:
            questions.append(f"Need evidence for: {claim.statement}")
        elif claim.status == ClaimSupportStatus.CONFLICTED:
            questions.append(f"Resolve conflicting evidence for: {claim.statement}")
    return list(dict.fromkeys(questions))


def _sentence_candidate(excerpt: str) -> str:
    normalized = " ".join(excerpt.split()).strip()
    for delimiter in ("。", ".", "！", "?", "？"):
        if delimiter in normalized:
            normalized = normalized.split(delimiter, 1)[0]
            break
    return normalized[:500]


def _shares_terms(left: str, right: str) -> bool:
    left_terms = {term.lower() for term in left.replace("，", " ").replace("。", " ").split() if len(term) >= 2}
    right_terms = {term.lower() for term in right.replace("，", " ").replace("。", " ").split() if len(term) >= 2}
    if not left_terms or not right_terms:
        return left[:24] in right or right[:24] in left
    return bool(left_terms & right_terms)


def _confidence_for(evidence_ids: list[str], records: list[EvidenceRecord]) -> float:
    reliability = {record.evidence_id: record.reliability for record in records}
    if not evidence_ids:
        return 0.0
    average = sum(reliability.get(evidence_id, 0.0) for evidence_id in evidence_ids) / len(evidence_ids)
    diversity_bonus = min(0.15, (len(evidence_ids) - 1) * 0.05)
    return min(0.98, average + diversity_bonus)
