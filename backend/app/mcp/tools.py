from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from app.mcp.search import (
    contributor_leaderboard,
    fetch_typed,
    health_ready,
    market_detail,
    material_detail,
    material_preview,
    material_recommendations,
    request_detail,
    request_leaderboard,
    search_all,
    search_market,
    search_materials,
    search_requests,
)


READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool(name="search", title="Search StudyHub", annotations=READ_ONLY, structured_output=True)
    def search(query: str, limit: int | None = 9) -> dict[str, Any]:
        """Use this when a user wants to search StudyHub materials, requests, and campus market items."""
        return search_all(query, limit)

    @mcp.tool(name="fetch", title="Fetch StudyHub Result", annotations=READ_ONLY, structured_output=True)
    def fetch(id: str) -> dict[str, Any]:
        """Use this when a user wants complete content for a StudyHub search result id."""
        return fetch_typed(id)

    @mcp.tool(name="materials.search", title="Search Materials", annotations=READ_ONLY, structured_output=True)
    def materials_search(query: str | None = None, limit: int | None = 5) -> dict[str, Any]:
        """Use this when a user specifically wants StudyHub learning materials."""
        return search_materials(query, limit)

    @mcp.tool(name="materials.get", title="Get Material", annotations=READ_ONLY, structured_output=True)
    def materials_get(id: int) -> dict[str, Any]:
        """Use this when a user wants one StudyHub material by numeric id."""
        return material_detail(id)

    @mcp.tool(name="materials.preview", title="Preview Material", annotations=READ_ONLY, structured_output=True)
    def materials_preview(id: int) -> dict[str, Any]:
        """Use this when a user wants public preview metadata for a StudyHub material."""
        return material_preview(id)

    @mcp.tool(name="materials.recommend", title="Recommend Materials", annotations=READ_ONLY, structured_output=True)
    def materials_recommend(limit: int | None = 6) -> dict[str, Any]:
        """Use this when a user wants StudyHub material recommendations."""
        return material_recommendations(limit)

    @mcp.tool(name="requests.search", title="Search Requests", annotations=READ_ONLY, structured_output=True)
    def requests_search(query: str | None = None, limit: int | None = 5) -> dict[str, Any]:
        """Use this when a user wants StudyHub material request or help-wanted posts."""
        return search_requests(query, limit)

    @mcp.tool(name="requests.get", title="Get Request", annotations=READ_ONLY, structured_output=True)
    def requests_get(id: int) -> dict[str, Any]:
        """Use this when a user wants one StudyHub request by numeric id."""
        return request_detail(id)

    @mcp.tool(name="requests.leaderboard", title="Request Leaderboard", annotations=READ_ONLY, structured_output=True)
    def requests_leaderboard(limit: int | None = 6) -> dict[str, Any]:
        """Use this when a user wants popular StudyHub requests."""
        return request_leaderboard(limit)

    @mcp.tool(name="market.search", title="Search Market", annotations=READ_ONLY, structured_output=True)
    def market_search(query: str | None = None, limit: int | None = 5) -> dict[str, Any]:
        """Use this when a user wants StudyHub campus market items."""
        return search_market(query, limit)

    @mcp.tool(name="market.get", title="Get Market Item", annotations=READ_ONLY, structured_output=True)
    def market_get(id: int) -> dict[str, Any]:
        """Use this when a user wants one StudyHub market item by numeric id."""
        return market_detail(id)

    @mcp.tool(name="leaderboard.contributors", title="Contributor Leaderboard", annotations=READ_ONLY, structured_output=True)
    def leaderboard_contributors(limit: int | None = 20, period: str | None = "all") -> dict[str, Any]:
        """Use this when a user wants StudyHub contributor rankings."""
        return contributor_leaderboard(limit, period)

    @mcp.tool(name="health.ready", title="StudyHub Readiness", annotations=READ_ONLY, structured_output=True)
    def health_ready_tool() -> dict[str, Any]:
        """Use this when a user wants to check StudyHub backend readiness."""
        return health_ready()
