from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.agentic_platform.deepresearch.state import ResearchTaskPacket
from app.agentic_platform.runtime.kernel import AgentKernel
from app.agentic_platform.subagents.deepresearch import DeepResearchSearchAgent
from app.models.agentic_runtime import AgentRunRecord

from .errors import AgentExecutionConfigurationError


BuildResultT = TypeVar("BuildResultT")
AgentKernelBuilder = Callable[[AgentRunRecord, dict[str, object]], AgentKernel | Awaitable[AgentKernel]]
DeepResearchAgentBuilder = Callable[
    [AgentRunRecord, ResearchTaskPacket],
    DeepResearchSearchAgent | Awaitable[DeepResearchSearchAgent],
]


class AgentRuntimeFactory:
    """Dependency-injected construction boundary for the execution worker.

    The factory deliberately has no scripted policy or fixed action path. R2
    wires a real model provider here; tests can provide bounded fixture
    builders without changing worker/job semantics.
    """

    def __init__(
        self,
        *,
        agent_kernel_builder: AgentKernelBuilder | None = None,
        deep_research_agent_builder: DeepResearchAgentBuilder | None = None,
    ) -> None:
        self._agent_kernel_builder = agent_kernel_builder
        self._deep_research_agent_builder = deep_research_agent_builder

    async def build_agent_kernel(
        self,
        *,
        run: AgentRunRecord,
        dispatch_payload: dict[str, object],
    ) -> AgentKernel:
        if self._agent_kernel_builder is None:
            raise AgentExecutionConfigurationError()
        built = self._agent_kernel_builder(run, dispatch_payload)
        return await _resolve(built)

    async def build_deep_research_agent(
        self,
        *,
        run: AgentRunRecord,
        research_task: ResearchTaskPacket,
    ) -> DeepResearchSearchAgent:
        if self._deep_research_agent_builder is None:
            raise AgentExecutionConfigurationError()
        built = self._deep_research_agent_builder(run, research_task)
        return await _resolve(built)


async def _resolve(value: BuildResultT | Awaitable[BuildResultT]) -> BuildResultT:
    if isinstance(value, Awaitable):
        return await value
    return value
