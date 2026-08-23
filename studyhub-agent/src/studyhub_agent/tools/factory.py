from __future__ import annotations

from dataclasses import dataclass

from studyhub_agent.adapters.collective_memory import CollectiveMemoryReader
from studyhub_agent.adapters.personal_memory import PersonalMemoryProvider
from studyhub_agent.adapters.rag import KnowledgeRetriever
from studyhub_agent.adapters.web import GuardedWebProviders
from studyhub_agent.tools.collective_memory import register_collective_memory_tool
from studyhub_agent.tools.knowledge import register_knowledge_tools
from studyhub_agent.tools.learning_state import register_personal_memory_tool
from studyhub_agent.tools.registry import ToolRegistry
from studyhub_agent.tools.web import register_web_tools


@dataclass(frozen=True, slots=True)
class ToolServices:
    knowledge: KnowledgeRetriever
    web: GuardedWebProviders
    personal_memory: PersonalMemoryProvider
    collective_memory: CollectiveMemoryReader


def build_tool_registry(services: ToolServices) -> ToolRegistry:
    registry = ToolRegistry()
    register_knowledge_tools(registry, services.knowledge)
    register_web_tools(registry, services.web)
    register_personal_memory_tool(registry, services.personal_memory)
    register_collective_memory_tool(registry, services.collective_memory)
    return registry
