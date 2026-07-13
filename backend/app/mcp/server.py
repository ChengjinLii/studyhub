from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import GetPromptRequest, ListPromptsRequest, ListResourcesRequest, ListResourceTemplatesRequest, ReadResourceRequest

from app.core.config import get_settings
from app.mcp.tools import register_tools


def create_studyhub_mcp() -> FastMCP:
    settings = get_settings()
    mcp = FastMCP(
        "StudyHub MCP",
        stateless_http=True,
        json_response=True,
        instructions=(
            "StudyHub exposes public material search, safe material detail, material recommendations, and platform policy. "
            "Always send users to the returned StudyHub page URL for login, purchase, and download."
        ),
    )
    mcp.settings.streamable_http_path = "/mcp"
    allowed_hosts = {"127.0.0.1:*", "localhost:*", "[::1]:*", f"{settings.host}:*", "testserver"}
    mcp.settings.transport_security.allowed_hosts = sorted(allowed_hosts)
    if settings.resolved_mcp_allowed_origins:
        mcp.settings.transport_security.allowed_origins = settings.resolved_mcp_allowed_origins
    register_tools(mcp)
    # FastMCP registers empty resource/prompt handlers by default. Remove those
    # handlers so initialize advertises the same tool-only surface enforced by
    # the HTTP authorization boundary.
    for request_type in (
        ListResourcesRequest,
        ListResourceTemplatesRequest,
        ReadResourceRequest,
        ListPromptsRequest,
        GetPromptRequest,
    ):
        mcp._mcp_server.request_handlers.pop(request_type, None)
    return mcp
