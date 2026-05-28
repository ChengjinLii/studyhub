from __future__ import annotations

from dataclasses import dataclass

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
