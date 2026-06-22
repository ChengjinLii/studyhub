from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from app.core.observability import get_runtime_metrics
from app.mcp.search import (
    contributor_leaderboard,
    discover_materials,
    fetch_typed,
    health_ready,
    market_detail,
    material_detail,
    material_recommendations,
    material_summary,
    public_material_recommendations,
    request_detail,
    request_leaderboard,
    search_all,
    search_market,
    search_materials,
    search_requests,
)


READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
logger = logging.getLogger(__name__)


def _call_tool(tool_name: str, handler, *args, **kwargs) -> dict[str, Any]:
    started_at = perf_counter()
    status = "ok"
    result_count = None
    try:
        result = handler(*args, **kwargs)
        if isinstance(result, dict):
            if isinstance(result.get("results"), list):
                result_count = len(result["results"])
            elif isinstance(result.get("items"), list):
                result_count = len(result["items"])
        return result
    except Exception:
        status = "error"
        raise
    finally:
        duration_seconds = perf_counter() - started_at
        get_runtime_metrics().record_mcp_tool_call(
            tool=tool_name,
            status=status,
            duration_seconds=duration_seconds,
        )
        logger.info(
            "MCP tool call completed",
            extra={
                "event": "mcp_tool_call",
                "tool": tool_name,
                "status": status,
                "duration_ms": round(duration_seconds * 1000, 2),
                "result_count": result_count,
            },
        )


def register_tools(mcp: FastMCP, *, include_ops_tools: bool = False) -> None:
    @mcp.tool(name="search", title="Search StudyHub", annotations=READ_ONLY, structured_output=True)
    def search(query: str, limit: int | None = 9) -> dict[str, Any]:
        """Use this when a user wants to search StudyHub materials, requests, and campus market items."""
        return _call_tool("search", search_all, query, limit)

    @mcp.tool(name="fetch", title="Fetch StudyHub Result", annotations=READ_ONLY, structured_output=True)
    def fetch(id: str) -> dict[str, Any]:
        """Use this when a user wants complete content for a StudyHub search result id."""
        return _call_tool("fetch", fetch_typed, id)

    @mcp.tool(name="materials.search", title="Search Materials", annotations=READ_ONLY, structured_output=True)
    def materials_search(query: str | None = None, limit: int | None = 5) -> dict[str, Any]:
        """Use this when a user specifically wants StudyHub learning materials."""
        return _call_tool("materials.search", search_materials, query, limit)

    @mcp.tool(name="materials.discover", title="Discover Materials", annotations=READ_ONLY, structured_output=True)
    def materials_discover(
        query: str | None = None,
        limit: int | None = 5,
        school: str | None = None,
        college: str | None = None,
        major: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        """Use this to recommend public StudyHub materials by returning lightweight metadata and StudyHub links, not downloads."""
        return _call_tool("materials.discover", discover_materials, query, limit, school, college, major, tag)

    @mcp.tool(name="materials.get", title="Get Material", annotations=READ_ONLY, structured_output=True)
    def materials_get(id: int) -> dict[str, Any]:
        """Use this when a user wants one StudyHub material by numeric id."""
        return _call_tool("materials.get", material_detail, id)

    @mcp.tool(name="materials.summarize", title="Summarize Material", annotations=READ_ONLY, structured_output=True)
    def materials_summarize(id: int) -> dict[str, Any]:
        """Use this to get a lightweight public StudyHub material summary and a StudyHub link, not a download."""
        return _call_tool("materials.summarize", material_summary, id)

    @mcp.tool(name="materials.recommend", title="Recommend Materials", annotations=READ_ONLY, structured_output=True)
    def materials_recommend(limit: int | None = 6) -> dict[str, Any]:
        """Use this when a user wants StudyHub material recommendations."""
        return _call_tool("materials.recommend", material_recommendations, limit)

    @mcp.tool(name="materials.recommend_public", title="Recommend Public Materials", annotations=READ_ONLY, structured_output=True)
    def materials_recommend_public(query: str | None = None, limit: int | None = 6) -> dict[str, Any]:
        """Use this for external agents to recommend public StudyHub materials with reasons and StudyHub links only."""
        return _call_tool("materials.recommend_public", public_material_recommendations, query, limit)

    @mcp.tool(name="requests.search", title="Search Requests", annotations=READ_ONLY, structured_output=True)
    def requests_search(query: str | None = None, limit: int | None = 5) -> dict[str, Any]:
        """Use this when a user wants StudyHub material request or help-wanted posts."""
        return _call_tool("requests.search", search_requests, query, limit)

    @mcp.tool(name="requests.get", title="Get Request", annotations=READ_ONLY, structured_output=True)
    def requests_get(id: int) -> dict[str, Any]:
        """Use this when a user wants one StudyHub request by numeric id."""
        return _call_tool("requests.get", request_detail, id)

    @mcp.tool(name="requests.leaderboard", title="Request Leaderboard", annotations=READ_ONLY, structured_output=True)
    def requests_leaderboard(limit: int | None = 6) -> dict[str, Any]:
        """Use this when a user wants popular StudyHub requests."""
        return _call_tool("requests.leaderboard", request_leaderboard, limit)

    @mcp.tool(name="market.search", title="Search Market", annotations=READ_ONLY, structured_output=True)
    def market_search(query: str | None = None, limit: int | None = 5) -> dict[str, Any]:
        """Use this when a user wants StudyHub campus market items."""
        return _call_tool("market.search", search_market, query, limit)

    @mcp.tool(name="market.get", title="Get Market Item", annotations=READ_ONLY, structured_output=True)
    def market_get(id: int) -> dict[str, Any]:
        """Use this when a user wants one StudyHub market item by numeric id."""
        return _call_tool("market.get", market_detail, id)

    @mcp.tool(name="leaderboard.contributors", title="Contributor Leaderboard", annotations=READ_ONLY, structured_output=True)
    def leaderboard_contributors(limit: int | None = 20, period: str | None = "all") -> dict[str, Any]:
        """Use this when a user wants StudyHub contributor rankings."""
        return _call_tool("leaderboard.contributors", contributor_leaderboard, limit, period)

    if include_ops_tools:
        @mcp.tool(name="health.ready", title="StudyHub Readiness", annotations=READ_ONLY, structured_output=True)
        def health_ready_tool() -> dict[str, Any]:
            """Use this for internal operations to check StudyHub backend readiness."""
            return _call_tool("health.ready", health_ready)
