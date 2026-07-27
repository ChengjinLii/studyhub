from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from pydantic import Field

from app.agentic_platform.deepresearch.graph import DeepResearchGraph, DeepResearchRunResult
from app.agentic_platform.deepresearch.state import ResearchPacket, ResearchReport, ResearchSourceType, ResearchTaskPacket
from app.agentic_platform.domain.decision import AgentActionType, AgentDecision
from app.agentic_platform.domain.observation import Observation, ObservationSource
from app.agentic_platform.domain.state import AgentTaskState, StateDelta

from .base import SubAgent, SubAgentResult

if TYPE_CHECKING:
    from app.agentic_platform.runtime.nodes import ActionExecutionResult


class DeepResearchSubAgentResult(SubAgentResult):
    research_packet: ResearchPacket
    research_report: ResearchReport
    terminal_reason: str = Field(min_length=1, max_length=2_000)
    child_transition_count: int = Field(default=0, ge=0)


class DeepResearchSearchAgent(SubAgent[ResearchTaskPacket, DeepResearchSubAgentResult]):
    """Isolated research worker: it receives only a ResearchTaskPacket.

    It neither reads a parent Thread nor writes the database.  The parent
    runtime may persist the returned packet/report as artifacts after applying
    its own permission and idempotency rules.
    """

    name = "deep_research"

    def __init__(self, graph: DeepResearchGraph, *, close_callbacks: list[Callable[[], object]] | None = None) -> None:
        self.graph = graph
        self._close_callbacks = list(close_callbacks or [])

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
            child_transition_count=result.child_transition_count,
        )

    def add_close_callbacks(self, callbacks: list[Callable[[], object]]) -> None:
        self._close_callbacks.extend(callbacks)

    async def close(self) -> None:
        callbacks, self._close_callbacks = self._close_callbacks, []
        for callback in callbacks:
            result = callback()
            if isinstance(result, Awaitable):
                await result

    @staticmethod
    def _summary(result: DeepResearchRunResult) -> str:
        validation = result.state.citation_validation
        if validation is not None:
            return validation.summary
        return f"Deep research finished with {len(result.packet.evidence)} evidence records."


def research_task_from_parent_decision(
    state: AgentTaskState,
    decision: AgentDecision,
    *,
    parent_transition_id: str,
) -> ResearchTaskPacket:
    """Translate a bounded parent delegate request without exposing its Thread."""

    if decision.action_type != AgentActionType.DELEGATE or decision.delegate_agent != "deep_research":
        raise ValueError("only a deep_research delegate decision can create a research task")
    if decision.task_packet is None:
        raise ValueError("deep_research delegate decision has no task packet")
    packet = decision.task_packet
    return ResearchTaskPacket(
        task_id=packet.task_id,
        admin_actor_id=state.admin_actor_id,
        research_question=packet.objective,
        allowed_source_types=[ResearchSourceType.INTERNAL_MATERIAL],
        max_turns=packet.max_turns,
        max_search_turns=min(packet.max_turns, 100),
        max_page_reads=min(max(packet.max_skill_calls, 1), 500),
        max_context_tokens=max(1, state.budget.context_tokens_remaining),
        input_artifacts=[item.model_copy(deep=True) for item in packet.input_artifacts],
        parent_transition_id=parent_transition_id,
    )


class DeepResearchDelegateExecutor:
    """Optional parent-runtime bridge for the ``deep_research`` delegate.

    It is deliberately one delegate adapter rather than a scheduler policy: the
    parent policy remains free to choose when to delegate and what bounded task
    packet to send.
    """

    def __init__(self, agent: DeepResearchSearchAgent) -> None:
        self.agent = agent

    async def execute(self, state: AgentTaskState, decision: AgentDecision, *, idempotency_key: str) -> "ActionExecutionResult":
        del state, decision, idempotency_key
        raise RuntimeError("deep_research delegate requires a parent transition ID")

    async def execute_with_parent_transition(
        self,
        state: AgentTaskState,
        decision: AgentDecision,
        *,
        idempotency_key: str,
        parent_transition_id: str,
    ) -> "ActionExecutionResult":
        del idempotency_key
        # Import at the integration boundary to keep the DeepResearch domain
        # independent from LangGraph runtime implementation details.
        from app.agentic_platform.runtime.nodes import ActionExecutionResult

        task = research_task_from_parent_decision(
            state,
            decision,
            parent_transition_id=parent_transition_id,
        )
        result = await self.agent.run(task)
        trace_ref = result.research_packet.trace_ref
        return ActionExecutionResult(
            state_delta=StateDelta(artifact_refs_to_add=[item.model_copy(deep=True) for item in result.artifact_refs]),
            observation=Observation(
                observation_id=f"deep-research:{result.task_id}",
                source=ObservationSource.SUBAGENT,
                summary=result.summary,
                artifact_ref=trace_ref.model_copy(deep=True),
            ),
            subagent_turns_used=result.turns_used,
        )
