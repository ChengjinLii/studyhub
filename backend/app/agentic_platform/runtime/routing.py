from __future__ import annotations

from enum import StrEnum

from app.agentic_platform.domain.decision import AgentActionType
from app.agentic_platform.domain.state import AgentTaskState


class KernelRoute(StrEnum):
    PLANNER = "planner"
    POLICY = "policy"
    SKILL_EXECUTOR = "skill_executor"
    SUBAGENT_EXECUTOR = "subagent_executor"
    INTERRUPT = "interrupt"
    EVENT_WAIT = "event_wait"
    VERIFIER = "verifier"
    CRITIC = "critic"
    FINALIZER = "finalizer"
    ARTIFACT_PERSIST = "artifact_persist"


def route_for_action(action_type: AgentActionType) -> KernelRoute:
    """Map a typed atomic action to a structural executor, never a business flow."""

    if action_type in {AgentActionType.CREATE_PLAN, AgentActionType.REVISE_PLAN}:
        return KernelRoute.PLANNER
    if action_type == AgentActionType.EXECUTE_SKILL:
        return KernelRoute.SKILL_EXECUTOR
    if action_type == AgentActionType.DELEGATE:
        return KernelRoute.SUBAGENT_EXECUTOR
    if action_type in {AgentActionType.ASK_USER, AgentActionType.REQUEST_APPROVAL}:
        return KernelRoute.INTERRUPT
    if action_type == AgentActionType.WAIT_EVENT:
        return KernelRoute.EVENT_WAIT
    if action_type in {AgentActionType.FINALIZE, AgentActionType.ABORT}:
        return KernelRoute.FINALIZER
    return KernelRoute.VERIFIER


def recursion_limit_for_state(state: AgentTaskState) -> int:
    """Give LangGraph enough scheduling room for the declared safety budget.

    This is deliberately derived from the agent's own budget rather than from a
    fixed replan/tool-loop ceiling.  The graph can therefore exercise every
    permitted turn and capability combination.
    """

    return max(
        64,
        16
        + state.budget.turns_remaining * 12
        + state.budget.skill_calls_remaining * 4
        + state.budget.subagent_turns_remaining * 6,
    )
