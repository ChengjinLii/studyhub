from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import json
from secrets import compare_digest
from typing import Any

from fastapi import Request
import jwt
from jwt import PyJWKClient

from app.core.config import Settings


SEARCH_MATERIALS_SCOPE = "mcp:materials.search"
READ_MATERIAL_SCOPE = "mcp:materials.read"
RECOMMEND_MATERIALS_SCOPE = "mcp:materials.recommend"
READ_PLATFORM_POLICY_SCOPE = "mcp:policy.read"

# Temporary aliases keep already-issued static integration tokens working while
# clients migrate to the four public OAuth scopes above.
DISCOVER_PUBLIC_MATERIALS_SCOPE = "mcp:discover_public_materials"
RECOMMEND_PUBLIC_MATERIALS_SCOPE = "mcp:recommend_public_materials"
READ_PUBLIC_MATERIAL_SUMMARY_SCOPE = "mcp:read_public_material_summary"


@dataclass(frozen=True)
class McpToolAccess:
    name: str
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class McpPrincipal:
    client_id: str
    subject: str | None
    scopes: frozenset[str]
    auth_method: str

    @property
    def quota_key(self) -> str:
        digest = sha256(f"{self.auth_method}:{self.client_id}".encode()).hexdigest()[:24]
        return f"{self.auth_method}:{digest}"


def public_mcp_scopes() -> tuple[str, ...]:
    return (
        SEARCH_MATERIALS_SCOPE,
        READ_MATERIAL_SCOPE,
        RECOMMEND_MATERIALS_SCOPE,
        READ_PLATFORM_POLICY_SCOPE,
    )


def _tool_access_registry(settings: Settings) -> dict[str, McpToolAccess]:
    read_alias = settings.mcp_read_scope
    return {
        "materials.search": McpToolAccess(
            "materials.search",
            (SEARCH_MATERIALS_SCOPE, DISCOVER_PUBLIC_MATERIALS_SCOPE, read_alias),
        ),
        "materials.get": McpToolAccess(
            "materials.get",
            (READ_MATERIAL_SCOPE, READ_PUBLIC_MATERIAL_SUMMARY_SCOPE, read_alias),
        ),
        "materials.recommend": McpToolAccess(
            "materials.recommend",
            (RECOMMEND_MATERIALS_SCOPE, RECOMMEND_PUBLIC_MATERIALS_SCOPE, read_alias),
        ),
        "platform.policy": McpToolAccess(
            "platform.policy",
            (READ_PLATFORM_POLICY_SCOPE, read_alias),
        ),
    }


def required_scopes_for_tool(settings: Settings, tool_name: str) -> set[str] | None:
    access = _tool_access_registry(settings).get(tool_name)
    return set(access.scopes) if access else None


def required_scope_for_tool(settings: Settings, tool_name: str) -> str | None:
    scopes = required_scopes_for_tool(settings, tool_name)
    return sorted(scopes)[0] if scopes else None


def _required_scopes_for_protocol_method(settings: Settings, method: str) -> set[str] | None:
    del settings
    if method in {"initialize", "notifications/initialized", "ping", "tools/list"}:
        return set(public_mcp_scopes())
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


def _static_principal(settings: Settings, token: str) -> McpPrincipal | None:
    for configured_token, scopes in _parse_access_tokens(settings):
        if compare_digest(token, configured_token):
            token_id = sha256(configured_token.encode()).hexdigest()[:20]
            return McpPrincipal(
                client_id=f"static-{token_id}",
                subject=None,
                scopes=frozenset(scopes),
                auth_method="static",
            )
    return None


@lru_cache(maxsize=8)
def _oauth_jwks_client(jwks_uri: str) -> PyJWKClient:
    return PyJWKClient(
        jwks_uri,
        cache_keys=True,
        max_cached_keys=16,
        cache_jwk_set=True,
        lifespan=300,
        timeout=5,
    )


def _oauth_signing_key(jwks_uri: str, token: str) -> Any:
    return _oauth_jwks_client(jwks_uri).get_signing_key_from_jwt(token).key


def _oauth_scopes(claims: dict[str, Any]) -> frozenset[str]:
    raw_scope = claims.get("scope")
    values: list[str] = []
    if isinstance(raw_scope, str):
        values.extend(raw_scope.split())
    raw_scp = claims.get("scp")
    if isinstance(raw_scp, str):
        values.extend(raw_scp.split())
    elif isinstance(raw_scp, list):
        values.extend(str(item) for item in raw_scp)
    return frozenset(value.strip() for value in values if value.strip())


def _oauth_principal(settings: Settings, token: str) -> McpPrincipal | None:
    if not (settings.mcp_oauth_jwks_uri and settings.mcp_oauth_issuer):
        return None
    try:
        signing_key = _oauth_signing_key(settings.mcp_oauth_jwks_uri, token)
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=settings.resolved_mcp_oauth_algorithms,
            audience=settings.resolved_mcp_oauth_audience,
            issuer=settings.mcp_oauth_issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except (jwt.PyJWTError, ValueError, TypeError):
        return None
    scopes = _oauth_scopes(dict(claims))
    client_id = str(claims.get("client_id") or claims.get("azp") or claims.get("sub") or "").strip()
    subject = str(claims.get("sub") or "").strip()
    if not client_id or not subject or not scopes:
        return None
    return McpPrincipal(
        client_id=client_id[:160],
        subject=subject[:200],
        scopes=scopes,
        auth_method="oauth",
    )


def authenticate_mcp_request(settings: Settings, request: Request) -> McpPrincipal | None:
    cached = getattr(request.state, "mcp_principal", None)
    if isinstance(cached, McpPrincipal):
        return cached
    token = _bearer_token(request)
    if not token:
        return None
    mode = settings.resolved_mcp_auth_mode
    principal = _static_principal(settings, token) if mode in {"static", "hybrid"} else None
    if principal is None and mode in {"oauth", "hybrid"}:
        principal = _oauth_principal(settings, token)
    if principal is not None:
        request.state.mcp_principal = principal
    return principal


def scopes_for_request(settings: Settings, request: Request) -> set[str] | None:
    principal = authenticate_mcp_request(settings, request)
    return set(principal.scopes) if principal else None


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
    if not isinstance(payload, dict) or payload.get("method") != "tools/call":
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
        if isinstance(params, dict) and isinstance(params.get("name"), str):
            return required_scopes_for_tool(settings, params["name"])
    return None


async def required_scope_for_request(settings: Settings, request: Request) -> str | None:
    scopes = await required_scopes_for_request(settings, request)
    return sorted(scopes)[0] if scopes else None


def _scope_allowed(granted_scopes: set[str], required_scopes: set[str]) -> bool:
    return bool(granted_scopes.intersection(required_scopes))


async def mcp_request_allowed(settings: Settings, request: Request) -> tuple[bool, str | None]:
    if not origin_allowed(settings, request.headers.get("origin")):
        return False, "MCP Origin is not allowed"
    payload = await _json_rpc_payload(request)
    if isinstance(payload, list):
        return False, "MCP batch requests are not allowed"
    required_scopes = await required_scopes_for_request(settings, request)
    if required_scopes is None:
        return False, "MCP method or tool is not allowed"
    if not settings.resolved_mcp_require_auth:
        request.state.mcp_principal = McpPrincipal(
            client_id="anonymous",
            subject=None,
            scopes=frozenset(public_mcp_scopes()),
            auth_method="anonymous",
        )
        return True, None
    principal = authenticate_mcp_request(settings, request)
    if principal is None:
        return False, "MCP authentication required"
    if not _scope_allowed(set(principal.scopes), required_scopes):
        return False, "MCP scope is not allowed"
    return True, None


def mcp_audit_identity(request: Request) -> dict[str, str | None]:
    principal = getattr(request.state, "mcp_principal", None)
    if not isinstance(principal, McpPrincipal):
        return {"client_id": None, "subject_hash": None, "auth_method": None}
    subject_hash = sha256(principal.subject.encode()).hexdigest()[:16] if principal.subject else None
    return {
        "client_id": principal.client_id[:80],
        "subject_hash": subject_hash,
        "auth_method": principal.auth_method,
    }
