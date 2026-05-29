from __future__ import annotations

from dataclasses import dataclass
from secrets import compare_digest

from fastapi import Request

from app.core.config import Settings


@dataclass(frozen=True)
class McpToolAccess:
    name: str
    scope: str
    mutating: bool
    admin: bool = False


WRITE_TOOL_REGISTRY = {
    "comments.create": McpToolAccess("comments.create", "studyhub.write", mutating=True),
    "requests.create": McpToolAccess("requests.create", "studyhub.write", mutating=True),
}

ADMIN_TOOL_REGISTRY = {
    "admin.users.search": McpToolAccess("admin.users.search", "studyhub.admin", mutating=False, admin=True),
    "admin.reports.search": McpToolAccess("admin.reports.search", "studyhub.admin", mutating=False, admin=True),
}


def origin_allowed(settings: Settings, origin: str | None) -> bool:
    if not origin:
        return True
    allowed = settings.resolved_mcp_allowed_origins
    if not allowed:
        return not (settings.is_preview or settings.is_production)
    return origin in allowed


def mcp_request_allowed(settings: Settings, request: Request) -> tuple[bool, str | None]:
    if not origin_allowed(settings, request.headers.get("origin")):
        return False, "MCP Origin is not allowed"
    if not settings.resolved_mcp_require_auth:
        return True, None
    configured_token = (settings.mcp_access_token or "").strip()
    if not configured_token:
        return False, "MCP access token is not configured"
    auth_header = request.headers.get("authorization") or ""
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not compare_digest(token.strip(), configured_token):
        return False, "MCP authentication required"
    return True, None
