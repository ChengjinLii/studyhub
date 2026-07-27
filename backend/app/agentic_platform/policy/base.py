from __future__ import annotations

from typing import Protocol

from app.agentic_platform.domain.decision import AgentDecision, AgentOutput
from app.agentic_platform.domain.plan import AgentPlan
from app.agentic_platform.domain.state import AgentTaskState

from .context_view import ContextView
from .turn_result import PolicyTurnResult


class AgentPolicy(Protocol):
    """Framework-independent planner, action policy, and finalizer contract."""

    async def create_plan(self, state: AgentTaskState, context: ContextView) -> PolicyTurnResult[AgentPlan]:
        ...

    async def decide(self, state: AgentTaskState, context: ContextView) -> PolicyTurnResult[AgentDecision]:
        ...

    async def finalize(self, state: AgentTaskState, context: ContextView) -> PolicyTurnResult[AgentOutput]:
        ...
