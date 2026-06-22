from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.core.config import get_settings
from app.mcp.prompts import register_prompts
from app.mcp.resources import register_resources
from app.mcp.tools import register_tools


def create_studyhub_mcp() -> FastMCP:
    settings = get_settings()
    mcp = FastMCP("StudyHub MCP", stateless_http=True, json_response=True)
    mcp.settings.streamable_http_path = "/mcp"
    allowed_hosts = {"127.0.0.1:*", "localhost:*", "[::1]:*", f"{settings.host}:*", "testserver"}
    mcp.settings.transport_security.allowed_hosts = sorted(allowed_hosts)
    if settings.resolved_mcp_allowed_origins:
        mcp.settings.transport_security.allowed_origins = settings.resolved_mcp_allowed_origins
    register_tools(mcp, include_ops_tools=settings.mcp_expose_ops_tools)
    register_resources(mcp)
    register_prompts(mcp)
    return mcp
