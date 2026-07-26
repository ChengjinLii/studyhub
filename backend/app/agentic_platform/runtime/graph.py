from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import START, StateGraph

from .nodes import AgentGraphNodes


class KernelGraphState(TypedDict, total=False):
    """Serializable scheduler state; ``task_state`` is the authoritative domain state."""

    task_state: dict[str, Any]
    decision: dict[str, Any]
    execution: dict[str, Any]
    final_output: dict[str, Any]
    verifier_result: dict[str, Any]
    turn_state_before: dict[str, Any]
    turn_delta: dict[str, Any]
    context_ref: dict[str, Any]
    context_catalog_hash: str
    action_fingerprints: list[str]
    observation_summaries: list[str]
    current_step_id: str | None
    pending_wait_id: str | None
    turn_index: int
    event_sequence: int
    duplicate_action: bool
    termination_status: str
    termination_reason: str
    cancel_requested: bool


def build_agent_graph(nodes: AgentGraphNodes, *, checkpointer: Any):
    """Build StudyHub's low-level graph without putting business plans in nodes."""

    graph = StateGraph(KernelGraphState)
    graph.add_node("bootstrap", nodes.bootstrap)
    graph.add_node("planner", nodes.planner)
    graph.add_node("policy", nodes.policy_node)
    graph.add_node("skill_executor", nodes.skill_executor_node)
    graph.add_node("subagent_executor", nodes.subagent_executor_node)
    graph.add_node("interrupt", nodes.interrupt_node)
    graph.add_node("event_wait", nodes.event_wait_node)
    graph.add_node("verifier", nodes.verifier_node)
    graph.add_node("critic", nodes.critic_node)
    graph.add_node("finalizer", nodes.finalizer_node)
    graph.add_node("artifact_persist", nodes.artifact_persist_node)
    graph.add_edge(START, "bootstrap")
    return graph.compile(checkpointer=checkpointer, name="studyhub-agent-kernel-v1")
