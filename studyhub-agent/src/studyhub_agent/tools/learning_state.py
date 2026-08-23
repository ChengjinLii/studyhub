from __future__ import annotations

from dataclasses import asdict

from studyhub_agent.adapters.personal_memory import PersonalMemoryProvider
from studyhub_agent.tools.registry import ToolExecutionContext, ToolRegistry


def register_personal_memory_tool(registry: ToolRegistry, provider: PersonalMemoryProvider) -> None:
    async def search(arguments: dict[str, object], context: ToolExecutionContext) -> dict[str, object]:
        records = provider.search(
            context.memory_namespace,
            str(arguments["query"]),
            limit=int(arguments["limit"]),
        )
        return {
            "memories": [
                {key: value for key, value in asdict(record).items() if key not in {"namespace"}} for record in records
            ]
        }

    registry.register("personal_memory_search", search)
