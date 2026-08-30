from types import SimpleNamespace

import pytest

from studyhub_agent.adapters.personal_memory import InMemoryPersonalMemoryProvider
from studyhub_agent.guardrails.budget import BudgetState
from studyhub_agent.integrations.hermes import (
    HermesRuntimeTools,
    constrain_hermes_tool_surface,
)
from studyhub_agent.runtime.session import TaskSpec
from studyhub_agent.tools.factory import DomainToolServices, build_domain_tool_registry
from studyhub_agent.tools.registry import ToolExecutionContext


def _context(identity, permissions, allowed_tools: list[str]) -> ToolExecutionContext:
    task = TaskSpec(
        task_id="tool-plan",
        family="composition",
        difficulty="medium",
        user_request="compose the minimum tool surface",
        environment_seed=11,
        allowed_tools=allowed_tools,
        max_steps=10,
        max_tool_calls=8,
    )
    return ToolExecutionContext(
        identity=identity,
        task=task,
        permissions=permissions,
        budget=BudgetState(max_steps=task.max_steps, max_tool_calls=task.max_tool_calls),
        memory_namespace=identity.personal_memory_namespace(case_id=task.task_id, seed=task.environment_seed),
    )


def test_runtime_plan_assigns_each_capability_to_one_owner(
    knowledge,
    collective_memory,
    identity,
    permissions,
) -> None:
    registry = build_domain_tool_registry(
        DomainToolServices(knowledge=knowledge, collective_memory=collective_memory)
    )
    context = _context(
        identity,
        permissions,
        [
            "knowledge_search",
            "web_search",
            "web_extract",
            "personal_memory_search",
            "collective_memory_search",
        ],
    )
    runtime = HermesRuntimeTools(registry, context, personal_memory=InMemoryPersonalMemoryProvider())

    assert runtime.plan.studyhub_tools == ("knowledge_search", "collective_memory_search")
    assert runtime.plan.native_tools == ("web_search", "web_extract")
    assert runtime.plan.memory_tools == ("personal_memory_search",)
    assert runtime.enabled_toolsets == ["studyhub", "web"]


def test_runtime_plan_rejects_replay_alias_and_missing_memory_provider(
    knowledge,
    collective_memory,
    identity,
    permissions,
) -> None:
    registry = build_domain_tool_registry(
        DomainToolServices(knowledge=knowledge, collective_memory=collective_memory)
    )

    with pytest.raises(ValueError, match="replay-only"):
        HermesRuntimeTools(registry, _context(identity, permissions, ["web_fetch"]))
    with pytest.raises(ValueError, match="requires a Hermes personal-memory provider"):
        HermesRuntimeTools(registry, _context(identity, permissions, ["personal_memory_search"]))


def test_tool_surface_projection_is_exact_and_fails_closed() -> None:
    agent = SimpleNamespace(
        tools=[
            {"type": "function", "function": {"name": "knowledge_search"}},
            {"type": "function", "function": {"name": "web_search"}},
            {"type": "function", "function": {"name": "unrelated_builtin"}},
        ],
        valid_tool_names={"knowledge_search", "web_search", "unrelated_builtin"},
    )

    constrain_hermes_tool_surface(agent, ("knowledge_search", "web_search"))

    assert agent.valid_tool_names == {"knowledge_search", "web_search"}
    assert [item["function"]["name"] for item in agent.tools] == ["knowledge_search", "web_search"]

    with pytest.raises(RuntimeError, match="did not expose"):
        constrain_hermes_tool_surface(agent, ("knowledge_search", "web_extract"))
