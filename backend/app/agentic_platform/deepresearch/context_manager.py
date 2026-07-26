from __future__ import annotations

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.hashing import canonical_json

from .state import DeepResearchState, ResearchContextAction, ResearchMemory, ResearchStateDelta


class ContextManagementResult(DomainModel):
    action: ResearchContextAction
    before_tokens: int
    after_tokens: int
    summary: str
    delta: ResearchStateDelta


class ResearchContextManager:
    """Changes only the active view; the evidence ledger remains append-only."""

    def estimate_tokens(self, state: DeepResearchState) -> int:
        active = set(state.research_memory.active_evidence_ids)
        visible = [record for record in state.evidence_ledger if record.evidence_id in active]
        rendered = canonical_json(
            {
                "question": state.research_question,
                "evidence": [
                    {
                        "evidence_id": record.evidence_id,
                        "title": record.title,
                        "page": record.page,
                        "excerpt": record.excerpt,
                    }
                    for record in visible
                ],
                "summaries": state.research_memory.summaries,
            },
            exclude_fields=(),
        )
        return max(1, (len(rendered) + 3) // 4)

    def activate_evidence(self, state: DeepResearchState, evidence_ids: list[str]) -> ResearchStateDelta:
        known = {record.evidence_id for record in state.evidence_ledger}
        known.update(evidence_ids)
        active = list(dict.fromkeys([*state.research_memory.active_evidence_ids, *[item for item in evidence_ids if item in known]]))
        archived = [item for item in state.research_memory.archived_evidence_ids if item not in set(active)]
        return ResearchStateDelta(
            research_memory=state.research_memory.model_copy(
                update={"active_evidence_ids": active, "archived_evidence_ids": archived}
            )
        )

    def apply(self, state: DeepResearchState, action: ResearchContextAction) -> ContextManagementResult:
        before = self.estimate_tokens(state)
        memory = state.research_memory.model_copy(deep=True)
        active = list(memory.active_evidence_ids)
        archived = list(memory.archived_evidence_ids)
        if action == ResearchContextAction.COMPRESS:
            keep = active[-1:] if active else []
            moved = active[:-1]
            records = {record.evidence_id: record for record in state.evidence_ledger}
            compact_titles = [records[item].title for item in moved if item in records]
            if moved:
                memory.summaries = [*memory.summaries, f"Compressed evidence: {', '.join(compact_titles)[:800]}"]
            active = keep
            archived = list(dict.fromkeys([*archived, *moved]))
            summary = f"Compressed {len(moved)} evidence records from the active context."
        elif action == ResearchContextAction.SNIPPET:
            active = active[-3:]
            archived = list(dict.fromkeys([*archived, *[item for item in memory.active_evidence_ids if item not in active]]))
            summary = "Kept a compact evidence snippet in the active context."
        elif action == ResearchContextAction.ROLLBACK:
            active = list(memory.active_evidence_ids)
            summary = "Retained the previous active context without deleting ledger evidence."
        elif action == ResearchContextAction.DROP:
            archived = list(dict.fromkeys([*archived, *active]))
            active = []
            summary = "Moved active evidence out of the working context while retaining the ledger."
        else:
            active = list(dict.fromkeys([*active, *archived]))
            archived = []
            summary = "Restored archived evidence into the active context."
        memory = memory.model_copy(
            update={
                "version": memory.version + 1,
                "active_evidence_ids": active,
                "archived_evidence_ids": archived,
                "last_action": action,
            }
        )
        successor = state.model_copy(update={"research_memory": memory})
        after = self.estimate_tokens(successor)
        return ContextManagementResult(
            action=action,
            before_tokens=before,
            after_tokens=after,
            summary=summary,
            delta=ResearchStateDelta(research_memory=memory),
        )
