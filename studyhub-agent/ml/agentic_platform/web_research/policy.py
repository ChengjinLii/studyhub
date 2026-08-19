from __future__ import annotations

from app.agentic_platform.deepresearch.state import (
    DeepResearchState,
    ResearchActionType,
    ResearchDecision,
    ResearchSourceRef,
    ResearchSourceType,
)
from app.agentic_platform.deepresearch.web_adapter import validate_web_query


_CURRENT_MARKERS = (
    "最新",
    "2026",
    "当前",
    "变化",
    "报名时间",
    "截稿时间",
    "法规",
    "标准",
    "版本",
)


class DeterministicWebRouterPolicy:
    """Auditable baseline for the frozen Web Router Gate, not a product policy."""

    policy_version = "studyhub-web-router-rule-v1"

    async def decide(self, state: DeepResearchState) -> ResearchDecision:
        if _contains_sensitive_externalization(state.research_question):
            return _decision(
                ResearchActionType.ABORT,
                "Reject externalization of credentials or account data.",
            )
        if (
            state.budget.remaining_search_turns <= 0
            and state.budget.remaining_page_reads <= 0
        ):
            return _decision(
                ResearchActionType.FINALIZE,
                "No search or page-read budget remains; finalize from collected evidence.",
            )
        unread_web = _unread_sources(state, ResearchSourceType.WEB)
        if unread_web and state.budget.remaining_page_reads > 0:
            return _decision(
                ResearchActionType.READ_WEB,
                "Read the selected external source before using its claims.",
                source_ids=[unread_web[0].source_id],
            )
        unread_internal = _unread_sources(state, ResearchSourceType.INTERNAL_MATERIAL)
        if unread_internal and state.budget.remaining_page_reads > 0:
            return _decision(
                ResearchActionType.READ_INTERNAL,
                "Read page-level evidence from the selected StudyHub material.",
                source_ids=[unread_internal[0].source_id],
            )
        if state.budget.remaining_search_turns > 0 and (
            _internal_search_was_empty(state) or _needs_current_web(state)
        ):
            query = _web_query(state)
            return _decision(
                ResearchActionType.SEARCH_WEB,
                "Use the external source only for the unresolved public-information gap.",
                query=query,
            )
        if state.budget.remaining_search_turns > 0:
            return _decision(
                ResearchActionType.SEARCH_INTERNAL,
                "Search StudyHub first for material discovery and learning evidence.",
                query=state.research_question,
            )
        return _decision(
            ResearchActionType.FINALIZE,
            "No valid research action remains within the frozen budget.",
        )


def _unread_sources(
    state: DeepResearchState, source_type: ResearchSourceType
) -> list[ResearchSourceRef]:
    evidence_uris = {item.source_uri for item in state.evidence_ledger}
    evidence_material_ids = {
        item.material_id
        for item in state.evidence_ledger
        if item.material_id is not None
    }
    return [
        source
        for source in state.visited_sources
        if source.source_type == source_type
        and source.source_uri not in evidence_uris
        and (
            source.material_id is None
            or source.material_id not in evidence_material_ids
        )
    ]


def _internal_search_was_empty(state: DeepResearchState) -> bool:
    return any(
        attempt.source_type == ResearchSourceType.INTERNAL_MATERIAL
        and attempt.result_count == 0
        for attempt in state.search_history
    )


def _needs_current_web(state: DeepResearchState) -> bool:
    text = " ".join([state.research_question, *state.unresolved_questions])
    return any(marker in text for marker in _CURRENT_MARKERS)


def _web_query(state: DeepResearchState) -> str:
    candidates = [*state.unresolved_questions, state.research_question]
    for candidate in candidates:
        if any(marker in candidate for marker in _CURRENT_MARKERS):
            return validate_web_query(candidate)
    return validate_web_query(state.research_question)


def _contains_sensitive_externalization(text: str) -> bool:
    try:
        validate_web_query(text)
    except Exception:  # noqa: BLE001 - use the runtime query validator as the baseline authority.
        return True
    return False


def _decision(
    action: ResearchActionType,
    rationale: str,
    *,
    query: str | None = None,
    source_ids: list[str] | None = None,
) -> ResearchDecision:
    return ResearchDecision(
        action_type=action,
        rationale_summary=rationale,
        query=query,
        source_ids=source_ids or [],
    )


__all__ = ["DeterministicWebRouterPolicy"]
