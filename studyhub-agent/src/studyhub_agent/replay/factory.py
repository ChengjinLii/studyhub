from __future__ import annotations

from dataclasses import dataclass

from studyhub_agent.adapters.collective_memory import CollectiveMemoryReader
from studyhub_agent.adapters.personal_memory import PersonalMemoryProvider
from studyhub_agent.adapters.rag import KnowledgeRetriever
from studyhub_agent.replay.handlers import register_replay_personal_memory_tool, register_replay_web_tools
from studyhub_agent.replay.web_providers import GuardedWebProviders
from studyhub_agent.tools.collective_memory import register_collective_memory_tool
from studyhub_agent.tools.knowledge import register_knowledge_tools
from studyhub_agent.tools.registry import ToolRegistry
from studyhub_agent.tools.schemas import TOOL_DEFINITIONS


@dataclass(frozen=True, slots=True)
class ReplayToolServices:
    """Services used only by frozen deterministic fixtures and old experiments."""

    knowledge: KnowledgeRetriever
    web: GuardedWebProviders
    personal_memory: PersonalMemoryProvider
    collective_memory: CollectiveMemoryReader


def build_replay_tool_registry(services: ReplayToolServices) -> ToolRegistry:
    """Reproduce schema-v1 fixture behavior without widening production tools."""
    registry = ToolRegistry(TOOL_DEFINITIONS)
    register_knowledge_tools(registry, services.knowledge)
    register_replay_web_tools(registry, services.web)
    register_replay_personal_memory_tool(registry, services.personal_memory)
    register_collective_memory_tool(registry, services.collective_memory)
    return registry
