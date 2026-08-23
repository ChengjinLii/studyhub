from __future__ import annotations

from studyhub_agent.guardrails.citation import extract_citations


def score_citations(
    final_answer: str,
    available_source_ids: set[str],
    *,
    citations_required: bool,
) -> tuple[float, list[str]]:
    cited = set(extract_citations(final_answer))
    invalid = sorted(cited - available_source_ids)
    violations = ["invalid_citation"] if invalid else []
    if not cited:
        return (-1.0 if citations_required else 1.0), violations + (["missing_citation"] if citations_required else [])
    valid_ratio = len(cited - set(invalid)) / len(cited)
    return (2.0 * valid_ratio) - 1.0, violations


def score_grounding(*, supported_claims: int, total_claims: int) -> float:
    if supported_claims < 0 or total_claims < 0 or supported_claims > total_claims:
        raise ValueError("invalid grounded-claim counts")
    if total_claims == 0:
        return 1.0
    return (2.0 * supported_claims / total_claims) - 1.0
