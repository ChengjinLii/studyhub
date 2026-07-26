from __future__ import annotations

from pydantic import Field

from app.agentic_platform.deepresearch.graph import DeepResearchGraph, DeepResearchRunResult
from app.agentic_platform.deepresearch.state import ResearchPacket, ResearchReport, ResearchTaskPacket

from .base import SubAgent, SubAgentResult


class DeepResearchSubAgentResult(SubAgentResult):
    research_packet: ResearchPacket
    research_report: ResearchReport
    terminal_reason: str = Field(min_length=1, max_length=2_000)


class DeepResearchSearchAgent(SubAgent[ResearchTaskPacket, DeepResearchSubAgentResult]):
    """Isolated research worker: it receives only a ResearchTaskPacket.

    It neither reads a parent Thread nor writes the database.  The parent
    runtime may persist the returned packet/report as artifacts after applying
    its own permission and idempotency rules.
    """

    name = "deep_research"

    def __init__(self, graph: DeepResearchGraph) -> None:
        self.graph = graph

    async def run(self, task: ResearchTaskPacket) -> DeepResearchSubAgentResult:
        result = await self.graph.run(task)
        return DeepResearchSubAgentResult(
            task_id=task.task_id,
            subagent_name=self.name,
            parent_transition_id=task.parent_transition_id,
            summary=self._summary(result),
            artifact_refs=[result.packet.trace_ref],
            turns_used=task.max_turns - result.state.budget.remaining_turns,
            research_packet=result.packet,
            research_report=result.report,
            terminal_reason=result.terminal_reason,
        )

    @staticmethod
    def _summary(result: DeepResearchRunResult) -> str:
        validation = result.state.citation_validation
        if validation is not None:
            return validation.summary
        return f"Deep research finished with {len(result.packet.evidence)} evidence records."
