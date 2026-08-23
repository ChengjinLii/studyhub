from __future__ import annotations

from studyhub_agent.adapters.web import GuardedWebProviders
from studyhub_agent.tools.registry import ToolExecutionContext, ToolRegistry


def register_web_tools(registry: ToolRegistry, providers: GuardedWebProviders) -> None:
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
