from __future__ import annotations

from fastapi import Request

from app.core.config import Settings
from app.core.rate_limit import client_key_for_request, rate_limit_key_allowed
from app.mcp.auth import McpPrincipal


def check_mcp_client_budget(settings: Settings, request: Request) -> tuple[bool, str | None, int | None]:
    principal = getattr(request.state, "mcp_principal", None)
    if isinstance(principal, McpPrincipal):
        client_key = principal.quota_key
    else:
        client_key = f"anonymous:{client_key_for_request(settings, request)}"

    minute_window = max(1, int(settings.rate_limit_window_seconds))
    if not rate_limit_key_allowed(
        settings,
        f"mcp-client-rate:{client_key}",
        limit=max(0, int(settings.mcp_client_rate_limit)),
        window_seconds=minute_window,
    ):
        return False, "MCP client rate limit exceeded", minute_window

    quota_window = max(60, int(settings.mcp_client_quota_window_seconds))
    if not rate_limit_key_allowed(
        settings,
        f"mcp-client-quota:{client_key}",
        limit=max(0, int(settings.mcp_client_quota)),
        window_seconds=quota_window,
    ):
        return False, "MCP client quota exceeded", quota_window
    return True, None, None
