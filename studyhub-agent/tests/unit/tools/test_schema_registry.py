import asyncio

import pytest

from studyhub_agent.adapters.personal_memory import PersonalMemoryProvider
from studyhub_agent.guardrails.budget import BudgetState
from studyhub_agent.replay import ReplayToolServices, build_replay_tool_registry
from studyhub_agent.tools.factory import DomainToolServices, build_domain_tool_registry
from studyhub_agent.tools.registry import ToolExecutionContext, ToolValidationError, validate_arguments
from studyhub_agent.tools.schemas import STUDYHUB_DOMAIN_TOOL_NAMES, TOOL_DEFINITIONS, TOOL_SCHEMA_VERSION

EXPECTED_TOOLS = {
    "knowledge_search",
    "knowledge_read",
    "knowledge_browse",
    "web_search",
    "web_fetch",
    "personal_memory_search",
    "collective_memory_search",
}


def test_tool_schema_v1_is_complete_and_strict() -> None:
    assert TOOL_SCHEMA_VERSION == "v1"
    assert set(TOOL_DEFINITIONS) == EXPECTED_TOOLS
    assert all(definition.parameters["additionalProperties"] is False for definition in TOOL_DEFINITIONS.values())
    with pytest.raises(ToolValidationError):
        validate_arguments(TOOL_DEFINITIONS["knowledge_search"], {"query": "CPS", "unknown": True})
    with pytest.raises(ToolValidationError):
        validate_arguments(TOOL_DEFINITIONS["knowledge_browse"], {})


def test_registry_dispatches_fixture_capabilities_without_acl_leak(
    knowledge,
    web,
    personal_memory: PersonalMemoryProvider,
    collective_memory,
    identity,
    permissions,
) -> None:
    namespace = identity.personal_memory_namespace(case_id="case-a", seed=9)
    personal_memory.add(namespace, "用户偏好按题型刷通信原理真题")
    registry = build_replay_tool_registry(
        ReplayToolServices(
            knowledge=knowledge,
            web=web,
            personal_memory=personal_memory,
            collective_memory=collective_memory,
        )
    )
    from studyhub_agent.runtime.session import TaskSpec

    task = TaskSpec(
        task_id="case-a",
        family="rag_web_memory",
        difficulty="medium",
        user_request="两周后考通信原理",
        environment_seed=9,
        allowed_tools=sorted(EXPECTED_TOOLS),
        max_steps=12,
        max_tool_calls=8,
    )
    context = ToolExecutionContext(
        identity=identity,
        task=task,
        permissions=permissions,
        budget=BudgetState(max_steps=12, max_tool_calls=8),
        memory_namespace=namespace,
    )

    rag_result = asyncio.run(registry.dispatch("knowledge_search", {"query": "通信原理 真题"}, context))
    web_result = asyncio.run(registry.dispatch("web_search", {"query": "通信原理 复习"}, context))
    memory_result = asyncio.run(registry.dispatch("personal_memory_search", {"query": "真题"}, context))

    assert rag_result["results"]
    assert all(result["material_id"] != 130 for result in rag_result["results"])
    assert web_result["results"][0]["url"].startswith("https://")
    assert memory_result["memories"][0]["content"].startswith("用户偏好")
    assert "namespace" not in memory_result["memories"][0]
    assert context.budget.tool_calls == 3


def test_production_registry_contains_only_studyhub_domain_tools(knowledge, collective_memory) -> None:
    registry = build_domain_tool_registry(
        DomainToolServices(knowledge=knowledge, collective_memory=collective_memory)
    )

    assert registry.names == STUDYHUB_DOMAIN_TOOL_NAMES
    assert "web_search" not in registry.names
    assert "personal_memory_search" not in registry.names
