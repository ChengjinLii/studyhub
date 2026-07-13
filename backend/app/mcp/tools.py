from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from app.core.observability import get_runtime_metrics
from app.mcp.search import material_detail, platform_policy, public_material_recommendations, search_materials


READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
logger = logging.getLogger(__name__)


def _call_tool(tool_name: str, handler, *args, **kwargs) -> dict[str, Any]:
    started_at = perf_counter()
    status = "ok"
    result_count = None
    try:
        result = handler(*args, **kwargs)
        if isinstance(result, dict) and isinstance(result.get("items"), list):
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


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool(name="materials.search", title="Search StudyHub Materials", annotations=READ_ONLY, structured_output=True)
    def materials_search(
        query: str,
        course: str | None = None,
        goal: str | None = None,
        material_type: str | None = None,
        school: str | None = None,
        college: str | None = None,
        major: str | None = None,
        tag: str | None = None,
        limit: int | None = 5,
    ) -> dict[str, Any]:
        """Search public StudyHub material metadata. Returns StudyHub detail links only, never files or download URLs."""
        return _call_tool(
            "materials.search",
            search_materials,
            query,
            limit,
            course=course,
            goal=goal,
            material_type=material_type,
            school=school,
            college=college,
            major=major,
            tag=tag,
        )

    @mcp.tool(name="materials.get", title="Get StudyHub Material Detail", annotations=READ_ONLY, structured_output=True)
    def materials_get(material_id: int) -> dict[str, Any]:
        """Get safe public metadata and the StudyHub detail-page link for one material; never returns protected content."""
        return _call_tool("materials.get", material_detail, material_id)

    @mcp.tool(name="materials.recommend", title="Recommend StudyHub Materials", annotations=READ_ONLY, structured_output=True)
    def materials_recommend(
        query: str,
        course: str | None = None,
        goal: str | None = None,
        time_budget: str | None = None,
        material_type: str | None = None,
        school: str | None = None,
        college: str | None = None,
        major: str | None = None,
        limit: int | None = 5,
    ) -> dict[str, Any]:
        """Recommend public StudyHub materials for a learning goal. Users open returned links to log in, pay, or download."""
        return _call_tool(
            "materials.recommend",
            public_material_recommendations,
            query,
            limit,
            course=course,
            goal=goal,
            time_budget=time_budget,
            material_type=material_type,
            school=school,
            college=college,
            major=major,
        )

    @mcp.tool(name="platform.policy", title="Read StudyHub Platform Policy", annotations=READ_ONLY, structured_output=True)
    def read_platform_policy(question: str) -> dict[str, Any]:
        """Answer public StudyHub upload, download, payment, copyright, review, and account-policy questions."""
        return _call_tool("platform.policy", platform_policy, question)
