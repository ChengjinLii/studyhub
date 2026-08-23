from __future__ import annotations

from studyhub_agent.adapters.rag import KnowledgeRetriever
from studyhub_agent.tools.registry import ToolExecutionContext, ToolRegistry


def register_knowledge_tools(registry: ToolRegistry, retriever: KnowledgeRetriever) -> None:
    async def search(arguments: dict[str, object], context: ToolExecutionContext) -> dict[str, object]:
        results = await retriever.search(
            str(arguments["query"]),
            limit=int(arguments["limit"]),
            permissions=context.permissions,
        )
        return {"results": [result.to_public_dict() for result in results]}

    async def read(arguments: dict[str, object], context: ToolExecutionContext) -> dict[str, object]:
        result = await retriever.read(str(arguments["source_id"]), permissions=context.permissions)
        return {"result": result.to_public_dict() if result else None}

    async def browse(arguments: dict[str, object], context: ToolExecutionContext) -> dict[str, object]:
        results = await retriever.browse(
            material_id=int(arguments["material_id"]) if arguments.get("material_id") else None,
            source_id=str(arguments["source_id"]) if arguments.get("source_id") else None,
            limit=int(arguments["limit"]),
            permissions=context.permissions,
        )
        return {"results": [result.to_public_dict() for result in results]}

    registry.register("knowledge_search", search)
    registry.register("knowledge_read", read)
    registry.register("knowledge_browse", browse)
