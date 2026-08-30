from __future__ import annotations

from dataclasses import asdict

from studyhub_agent.adapters.personal_memory import PersonalMemoryProvider
from studyhub_agent.replay.web_providers import GuardedWebProviders
from studyhub_agent.tools.registry import ToolExecutionContext, ToolRegistry


def register_replay_web_tools(registry: ToolRegistry, providers: GuardedWebProviders) -> None:
    async def search(arguments: dict[str, object], context: ToolExecutionContext) -> dict[str, object]:
        del context
        return {
            "results": await providers.search(
                str(arguments["query"]),
                limit=int(arguments["limit"]),
            )
        }

    async def fetch(arguments: dict[str, object], context: ToolExecutionContext) -> dict[str, object]:
        del context
        return {"result": await providers.fetch(str(arguments["url"]))}

    registry.register("web_search", search)
    registry.register("web_fetch", fetch)


def register_replay_personal_memory_tool(registry: ToolRegistry, provider: PersonalMemoryProvider) -> None:
    async def search(arguments: dict[str, object], context: ToolExecutionContext) -> dict[str, object]:
        records = provider.search(
            context.memory_namespace,
            str(arguments["query"]),
            limit=int(arguments["limit"]),
        )
        return {
            "memories": [
                {key: value for key, value in asdict(record).items() if key != "namespace"} for record in records
            ]
        }

    registry.register("personal_memory_search", search)
