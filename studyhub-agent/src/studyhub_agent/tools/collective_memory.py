from __future__ import annotations

from dataclasses import asdict

from studyhub_agent.adapters.collective_memory import CollectiveMemoryReader
from studyhub_agent.guardrails.privacy import sanitize_output
from studyhub_agent.tools.registry import ToolExecutionContext, ToolRegistry


def register_collective_memory_tool(registry: ToolRegistry, reader: CollectiveMemoryReader) -> None:
    async def search(arguments: dict[str, object], context: ToolExecutionContext) -> dict[str, object]:
        del context
        results = reader.search(
            str(arguments["query"]),
            course=str(arguments.get("course", "")),
            limit=int(arguments["limit"]),
        )
        return {"results": [sanitize_output(asdict(result)) for result in results]}

    registry.register("collective_memory_search", search)
