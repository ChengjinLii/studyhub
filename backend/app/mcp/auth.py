from __future__ import annotations

from dataclasses import dataclass
import json
from secrets import compare_digest

from fastapi import Request

from app.core.config import Settings


@dataclass(frozen=True)
class McpToolAccess:
    name: str
    scopes: tuple[str, ...]
    mutating: bool
    admin: bool = False


DISCOVER_PUBLIC_MATERIALS_SCOPE = "mcp:discover_public_materials"
RECOMMEND_PUBLIC_MATERIALS_SCOPE = "mcp:recommend_public_materials"
READ_PUBLIC_MATERIAL_SUMMARY_SCOPE = "mcp:read_public_material_summary"
READ_PUBLIC_LEADERBOARD_SCOPE = "mcp:read_public_leaderboard"
MCP_OPS_SCOPE = "mcp:ops"


def _public_discovery_scopes(settings: Settings) -> tuple[str, ...]:
    return (settings.mcp_read_scope, DISCOVER_PUBLIC_MATERIALS_SCOPE)


def _public_summary_scopes(settings: Settings) -> tuple[str, ...]:
    return (settings.mcp_read_scope, READ_PUBLIC_MATERIAL_SUMMARY_SCOPE)


def _public_recommend_scopes(settings: Settings) -> tuple[str, ...]:
    return (settings.mcp_read_scope, RECOMMEND_PUBLIC_MATERIALS_SCOPE)


def _public_leaderboard_scopes(settings: Settings) -> tuple[str, ...]:
    return (settings.mcp_read_scope, READ_PUBLIC_LEADERBOARD_SCOPE)


def _tool_access_registry(settings: Settings) -> dict[str, McpToolAccess]:
    registry = {
        "search": McpToolAccess("search", _public_discovery_scopes(settings), mutating=False),
        "fetch": McpToolAccess("fetch", _public_summary_scopes(settings), mutating=False),
        "materials.search": McpToolAccess("materials.search", _public_discovery_scopes(settings), mutating=False),
        "materials.discover": McpToolAccess("materials.discover", _public_discovery_scopes(settings), mutating=False),
        "materials.get": McpToolAccess("materials.get", _public_summary_scopes(settings), mutating=False),
        "materials.summarize": McpToolAccess("materials.summarize", _public_summary_scopes(settings), mutating=False),
        "materials.recommend": McpToolAccess("materials.recommend", _public_recommend_scopes(settings), mutating=False),
        "materials.recommend_public": McpToolAccess(
            "materials.recommend_public",
            _public_recommend_scopes(settings),
            mutating=False,
        ),
        "requests.search": McpToolAccess("requests.search", _public_discovery_scopes(settings), mutating=False),
        "requests.get": McpToolAccess("requests.get", _public_summary_scopes(settings), mutating=False),
        "requests.leaderboard": McpToolAccess("requests.leaderboard", _public_leaderboard_scopes(settings), mutating=False),
        "market.search": McpToolAccess("market.search", _public_discovery_scopes(settings), mutating=False),
        "market.get": McpToolAccess("market.get", _public_summary_scopes(settings), mutating=False),
        "leaderboard.contributors": McpToolAccess(
            "leaderboard.contributors",
            _public_leaderboard_scopes(settings),
            mutating=False,
        ),
        "comments.create": McpToolAccess("comments.create", (settings.mcp_write_scope,), mutating=True),
        "requests.create": McpToolAccess("requests.create", (settings.mcp_write_scope,), mutating=True),
        "admin.users.search": McpToolAccess("admin.users.search", (settings.mcp_admin_scope,), mutating=False, admin=True),
        "admin.reports.search": McpToolAccess("admin.reports.search", (settings.mcp_admin_scope,), mutating=False, admin=True),
    }
    if settings.mcp_expose_ops_tools:
        registry["health.ready"] = McpToolAccess("health.ready", (MCP_OPS_SCOPE,), mutating=False)
    return registry


def required_scopes_for_tool(settings: Settings, tool_name: str) -> set[str] | None:
    access = _tool_access_registry(settings).get(tool_name)
    if access is None:
        return None
    return set(access.scopes)


def required_scope_for_tool(settings: Settings, tool_name: str) -> str | None:
    scopes = required_scopes_for_tool(settings, tool_name)
    if not scopes:
        return None
    return sorted(scopes)[0]


def _required_scopes_for_protocol_method(settings: Settings, method: str) -> set[str] | None:
    public_list_scopes = {
        settings.mcp_read_scope,
        DISCOVER_PUBLIC_MATERIALS_SCOPE,
        RECOMMEND_PUBLIC_MATERIALS_SCOPE,
        READ_PUBLIC_MATERIAL_SUMMARY_SCOPE,
        READ_PUBLIC_LEADERBOARD_SCOPE,
    }
    if method in {"initialize", "tools/list", "prompts/list", "prompts/get"}:
        return public_list_scopes
    if method in {"resources/list", "resources/templates/list", "resources/read"}:
        return {settings.mcp_read_scope, READ_PUBLIC_MATERIAL_SUMMARY_SCOPE}
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


async def _json_rpc_payload(request: Request) -> dict | list | None:
    if request.method.upper() != "POST":
        return None
    try:
        payload = json.loads((await request.body()).decode("utf-8") or "{}")
    except Exception:
        return None
    return payload if isinstance(payload, (dict, list)) else None


async def requested_tool_name(request: Request) -> str | None:
    payload = await _json_rpc_payload(request)
    if not isinstance(payload, dict):
        return None
    if payload.get("method") != "tools/call":
        return None
    params = payload.get("params")
    if not isinstance(params, dict):
        return None
    name = params.get("name")
    return name if isinstance(name, str) else None


async def required_scopes_for_request(settings: Settings, request: Request) -> set[str] | None:
    payload = await _json_rpc_payload(request)
    if not isinstance(payload, dict):
        return None
    method = payload.get("method")
    if isinstance(method, str):
        method_scopes = _required_scopes_for_protocol_method(settings, method)
        if method_scopes is not None:
            return method_scopes
    if method == "tools/call":
        params = payload.get("params")
        if not isinstance(params, dict):
            return None
        tool_name = params.get("name")
        if isinstance(tool_name, str):
            return required_scopes_for_tool(settings, tool_name)
    return None


async def required_scope_for_request(settings: Settings, request: Request) -> str | None:
    scopes = await required_scopes_for_request(settings, request)
    if not scopes:
        return None
    return sorted(scopes)[0]


def _scope_allowed(granted_scopes: set[str], required_scopes: set[str]) -> bool:
    return bool(granted_scopes.intersection(required_scopes))


async def mcp_request_allowed(settings: Settings, request: Request) -> tuple[bool, str | None]:
    if not origin_allowed(settings, request.headers.get("origin")):
        return False, "MCP Origin is not allowed"
    payload = await _json_rpc_payload(request)
    if isinstance(payload, list):
        return False, "MCP batch requests are not allowed"
    if not settings.resolved_mcp_require_auth:
        return True, None
    if not _parse_access_tokens(settings):
        return False, "MCP access token is not configured"
    scopes = scopes_for_request(settings, request)
    if scopes is None:
        return False, "MCP authentication required"
    required_scopes = await required_scopes_for_request(settings, request)
    if required_scopes is None:
        return False, "MCP method or tool is not allowed"
    if not _scope_allowed(scopes, required_scopes):
        return False, "MCP scope is not allowed"
    return True, None
