from __future__ import annotations

from dataclasses import dataclass

from studyhub_agent.adapters.collective_memory import CollectiveMemoryReader
from studyhub_agent.adapters.rag import KnowledgeRetriever
from studyhub_agent.tools.collective_memory import register_collective_memory_tool
from studyhub_agent.tools.knowledge import register_knowledge_tools
from studyhub_agent.tools.registry import ToolRegistry
from studyhub_agent.tools.schemas import STUDYHUB_DOMAIN_TOOL_DEFINITIONS


@dataclass(frozen=True, slots=True)
class DomainToolServices:
    knowledge: KnowledgeRetriever
    collective_memory: CollectiveMemoryReader


def build_domain_tool_registry(services: DomainToolServices) -> ToolRegistry:
    """Build the production StudyHub extension surface.

    General web tools and personal-memory lifecycle hooks are owned by Hermes
    and intentionally do not enter this registry.
    """
    registry = ToolRegistry(STUDYHUB_DOMAIN_TOOL_DEFINITIONS)
    register_knowledge_tools(registry, services.knowledge)
    register_collective_memory_tool(registry, services.collective_memory)
    return registry
