from __future__ import annotations

from dataclasses import dataclass
import json
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

READ_TOOL_NAMES = {
    "search",
    "fetch",
    "materials.search",
    "materials.get",
    "materials.preview",
    "materials.recommend",
    "requests.search",
    "requests.get",
    "requests.leaderboard",
    "market.search",
    "market.get",
    "leaderboard.contributors",
    "health.ready",
}
READ_METHODS = {"initialize", "tools/list", "resources/list", "resources/read", "prompts/list", "prompts/get"}


def required_scope_for_tool(settings: Settings, tool_name: str) -> str | None:
    if tool_name in READ_TOOL_NAMES:
        return settings.mcp_read_scope
    if tool_name in WRITE_TOOL_REGISTRY:
        return settings.mcp_write_scope
    if tool_name in ADMIN_TOOL_REGISTRY:
        return settings.mcp_admin_scope
    return None


def origin_allowed(settings: Settings, origin: str | None) -> bool:
    if not origin:
        return True
    allowed = settings.resolved_mcp_allowed_origins
    if not allowed:
        return not (settings.is_preview or settings.is_production)
    return origin in allowed


def _parse_access_tokens(settings: Settings) -> list[tuple[str, set[str]]]:
    tokens: list[tuple[str, set[str]]] = []
    if settings.mcp_access_tokens:
        for entry in settings.mcp_access_tokens.split(";"):
            raw_entry = entry.strip()
            if not raw_entry:
                continue
            token, _, raw_scopes = raw_entry.partition(":")
            clean_token = token.strip()
            scopes = {scope.strip() for scope in raw_scopes.split(",") if scope.strip()}
            if clean_token:
                tokens.append((clean_token, scopes or {settings.mcp_read_scope}))
    if settings.mcp_access_token:
        tokens.append((settings.mcp_access_token.strip(), {settings.mcp_read_scope}))
    return tokens


def _bearer_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization") or ""
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    clean_token = token.strip()
    return clean_token or None


def scopes_for_request(settings: Settings, request: Request) -> set[str] | None:
    token = _bearer_token(request)
    if not token:
        return None
    for configured_token, scopes in _parse_access_tokens(settings):
        if compare_digest(token, configured_token):
            return scopes
    return None


async def _json_rpc_payload(request: Request) -> dict | None:
    if request.method.upper() != "POST":
        return None
    try:
        payload = json.loads((await request.body()).decode("utf-8") or "{}")
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


async def requested_tool_name(request: Request) -> str | None:
    payload = await _json_rpc_payload(request)
    if payload is None:
        return None
    if payload.get("method") != "tools/call":
        return None
    params = payload.get("params")
    if not isinstance(params, dict):
        return None
    name = params.get("name")
    return name if isinstance(name, str) else None


async def required_scope_for_request(settings: Settings, request: Request) -> str | None:
    payload = await _json_rpc_payload(request)
    if payload is None:
        return None
    method = payload.get("method")
    if method in READ_METHODS:
        return settings.mcp_read_scope
    if method == "tools/call":
        params = payload.get("params")
        if not isinstance(params, dict):
            return None
        tool_name = params.get("name")
        if isinstance(tool_name, str):
            return required_scope_for_tool(settings, tool_name)
    return None


async def mcp_request_allowed(settings: Settings, request: Request) -> tuple[bool, str | None]:
    if not origin_allowed(settings, request.headers.get("origin")):
        return False, "MCP Origin is not allowed"
    if not settings.resolved_mcp_require_auth:
        return True, None
    if not _parse_access_tokens(settings):
        return False, "MCP access token is not configured"
    scopes = scopes_for_request(settings, request)
    if scopes is None:
        return False, "MCP authentication required"
    required_scope = await required_scope_for_request(settings, request)
    if required_scope and required_scope not in scopes:
        return False, "MCP scope is not allowed"
    return True, None
