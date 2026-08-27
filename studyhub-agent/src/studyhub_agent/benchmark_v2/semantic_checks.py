# ruff: noqa: E501 - public signatures retain the full evaluator contract
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_CITATION = re.compile(r"\[([^\[\]\n]{2,220})\]")
_SENTENCE = re.compile(r"[^。！？!?\n]+[。！？!?]?|[^\n]+$")
_NEGATION_PREFIX = re.compile(r"(?:并非|不是|不属于|不能算作|错误地称为|incorrect(?:ly)?|is\s+not|are\s+not|not)", re.I)


def normalize_text(value: str) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", " ", value.casefold()).strip()


def citations(value: str) -> list[str]:
    return _CITATION.findall(value)


def sentences(value: str) -> list[str]:
    return [segment.strip() for segment in _SENTENCE.findall(value) if segment.strip()]


def group_hit(text: str, alternatives: list[str]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(value) in normalized for value in alternatives if normalize_text(value))


def contradicted(text: str, patterns: list[str]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(pattern) in normalized for pattern in patterns if normalize_text(pattern))


@dataclass(frozen=True, slots=True)
class ClaimCheck:
    claim_id: str
    mentioned: bool
    contradicted: bool
    supported: bool
    attached_citations: tuple[str, ...]
    allowed_sources: tuple[str, ...]


def check_claims(
    answer: str, trace: dict[str, Any], claims: list[dict[str, Any]]
) -> tuple[list[ClaimCheck], dict[str, Any]]:
    answer_sentences = sentences(answer)
    read_sources = set(map(str, trace.get("read_source_ids", []))) | set(map(str, trace.get("fetched_urls", [])))
    checks: list[ClaimCheck] = []
    for claim in claims:
        groups = [list(map(str, group)) for group in claim.get("acceptable_semantic_answers", [])]
        matching = [sentence for sentence in answer_sentences if all(group_hit(sentence, group) for group in groups)]
        forbidden = list(map(str, claim.get("contradiction_patterns", [])))
        has_contradiction = any(contradicted(sentence, forbidden) for sentence in matching or answer_sentences)
        has_contradiction = has_contradiction or any(
            contains_negated_correct_answer(sentence, groups) for sentence in matching
        )
        allowed = set(map(str, claim.get("support_source_ids", [])))
        attached = {
            citation
            for sentence in matching
            for citation in citations(sentence)
            if citation in allowed and citation in read_sources
        }
        citation_required = bool(claim.get("citation_required", True))
        mentioned = bool(matching)
        supported = mentioned and not has_contradiction and (bool(attached) or not citation_required)
        checks.append(
            ClaimCheck(
                claim_id=str(claim.get("claim_id")),
                mentioned=mentioned,
                contradicted=has_contradiction,
                supported=supported,
                attached_citations=tuple(sorted(attached)),
                allowed_sources=tuple(sorted(allowed)),
            )
        )
    all_citations = citations(answer)
    allowed_all = {source for check in checks for source in check.allowed_sources}
    valid_citations = {source for check in checks for source in check.attached_citations}
    fabricated = sorted(set(all_citations) - read_sources)
    wrong_source = sorted((set(all_citations) & read_sources) - allowed_all)
    return checks, {
        "citations": all_citations,
        "valid_attached_citations": sorted(valid_citations),
        "fabricated_citations": fabricated,
        "wrong_source_citations": wrong_source,
        "read_sources": sorted(read_sources),
    }


def contains_negated_correct_answer(answer: str, accepted_groups: list[list[str]]) -> bool:
    for sentence in sentences(answer):
        normalized_sentence = normalize_text(sentence)
        if not all(group_hit(sentence, group) for group in accepted_groups):
            continue
        for group in accepted_groups:
            for alternative in group:
                normalized_alternative = normalize_text(alternative)
                if not normalized_alternative or normalized_alternative not in normalized_sentence:
                    continue
                if _NEGATION_PREFIX.search(alternative):
                    continue
                escaped = re.escape(alternative).replace(r"\ ", r"\s+")
                if re.search(rf"(?:并非|不是|不属于|错误地称为)\s*[^;；。！？!?]{{0,12}}{escaped}", sentence, re.I):
                    return True
                if re.search(
                    rf"(?:is\s+not|are\s+not|not|incorrect(?:ly)?)\s*[^;；.。！？!?]{{0,24}}{escaped}",
                    sentence,
                    re.I,
                ):
                    return True
    return False
