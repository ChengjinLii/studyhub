from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from app.agentic_platform.domain.decision import AgentDecision, AgentOutput
from app.agentic_platform.domain.plan import AgentPlan
from app.agentic_platform.domain.state import AgentTaskState
from app.agentic_platform.domain.hashing import canonical_hash

from .context_view import ContextPurpose, ContextView
from .turn_result import PolicyTurnResult, replay_turn


class ReplayScriptExhaustedError(LookupError):
    pass


class ReplayPolicy:
    """Deterministic policy for smoke tests, replay, and simulation without a model."""

    def __init__(
        self,
        *,
        plans: Iterable[AgentPlan] = (),
        decisions: Iterable[AgentDecision] = (),
        final_outputs: Iterable[AgentOutput] = (),
    ) -> None:
        self._plans = deque(plan.model_copy(deep=True) for plan in plans)
        self._decisions = deque(decision.model_copy(deep=True) for decision in decisions)
        self._final_outputs = deque(output.model_copy(deep=True) for output in final_outputs)

    async def create_plan(self, state: AgentTaskState, context: ContextView) -> PolicyTurnResult[AgentPlan]:
        self._assert_purpose(context, ContextPurpose.PLANNER)
        if self._plans:
            plan = self._plans.popleft()
        else:
            plan = state.plan.model_copy(deep=True)
        return replay_turn(
            parsed_output=plan,
            purpose=ContextPurpose.PLANNER,
            context_hash=canonical_hash(context),
        )

    async def decide(self, state: AgentTaskState, context: ContextView) -> PolicyTurnResult[AgentDecision]:
        del state
        self._assert_purpose(context, ContextPurpose.POLICY)
        if not self._decisions:
            raise ReplayScriptExhaustedError("replay decision script is exhausted")
        return replay_turn(
            parsed_output=self._decisions.popleft(),
            purpose=ContextPurpose.POLICY,
            context_hash=canonical_hash(context),
        )

    async def finalize(self, state: AgentTaskState, context: ContextView) -> PolicyTurnResult[AgentOutput]:
        self._assert_purpose(context, ContextPurpose.FINALIZER)
        if self._final_outputs:
            output = self._final_outputs.popleft()
        else:
            output = AgentOutput(summary=f"Replay completed for {state.run_id}", artifact_refs=list(state.active_artifacts))
        return replay_turn(
            parsed_output=output,
            purpose=ContextPurpose.FINALIZER,
            context_hash=canonical_hash(context),
        )

    @staticmethod
    def _assert_purpose(context: ContextView, expected: ContextPurpose) -> None:
        if context.purpose != expected:
            raise ValueError(f"replay policy expected {expected.value} context, got {context.purpose.value}")
