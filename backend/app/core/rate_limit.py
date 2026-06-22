from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from time import monotonic

from fastapi import Request

from app.core.config import Settings


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    limit: int


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def clear(self) -> None:
        self._hits.clear()

    def check(self, key: str, *, limit: int, window_seconds: int) -> bool:
        if limit <= 0:
            return True
        now = monotonic()
        window_start = now - max(1, window_seconds)
        bucket = self._hits[key]
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


_RATE_LIMITER = InMemoryRateLimiter()


def get_rate_limiter() -> InMemoryRateLimiter:
    return _RATE_LIMITER


def _is_trusted_proxy(settings: Settings, host: str | None) -> bool:
    if not host:
        return False
    try:
        remote_addr = ip_address(host)
    except ValueError:
        return False
    for raw_network in settings.resolved_trusted_proxy_ips:
        try:
            network = ip_network(raw_network, strict=False)
        except ValueError:
            continue
        if remote_addr in network:
            return True
    return False


def _client_key(settings: Settings, request: Request) -> str:
    remote_host = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _is_trusted_proxy(settings, remote_host):
        forwarded_host = forwarded.split(",", 1)[0].strip()
        try:
            return str(ip_address(forwarded_host))
        except ValueError:
            return forwarded_host or (remote_host or "unknown")
    return remote_host or "unknown"


def _rule_for_request(settings: Settings, request: Request) -> RateLimitRule | None:
    path = request.url.path
    method = request.method.upper()
    if path.startswith("/mcp"):
        return RateLimitRule("mcp", settings.rate_limit_mcp)
    if method == "POST" and path in {"/api/session", "/api/auth/login", "/api/dev-session", "/api/auth/dev-login"}:
        return RateLimitRule("login", settings.rate_limit_login)
    if method == "GET" and path in {"/api/captchas", "/api/captcha", "/api/auth/captcha"}:
        return RateLimitRule("captcha", settings.rate_limit_captcha)
    if method == "POST" and path in {"/api/registration-verifications", "/api/auth/register", "/api/password-resets", "/api/auth/reset-password"}:
        return RateLimitRule("email-verification", settings.rate_limit_email_verification)
    if method == "POST" and path in {"/api/materials", "/api/market"}:
        return RateLimitRule("upload", settings.rate_limit_upload)
    if method == "POST" and path.startswith("/api/materials/") and path.endswith(("/view", "/views")):
        return RateLimitRule("view", settings.rate_limit_view)
    return None


def rate_limit_allowed(settings: Settings, request: Request) -> tuple[bool, str | None]:
    if not settings.rate_limit_enabled:
        return True, None
    rule = _rule_for_request(settings, request)
    if rule is None:
        return True, None
    key = f"{rule.name}:{_client_key(settings, request)}"
    allowed = get_rate_limiter().check(key, limit=rule.limit, window_seconds=settings.rate_limit_window_seconds)
    if allowed:
        return True, None
    return False, f"Too many {rule.name} requests"
