from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
import secrets
from time import monotonic, time
from typing import Any

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


class RedisRateLimiter:
    _CHECK_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  redis.call('EXPIRE', key, math.ceil(window))
  return 0
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window))
return 1
"""

    def __init__(self) -> None:
        self._redis_client: Any | None = None

    def clear(self) -> None:
        self._redis_client = None

    def check(self, settings: Settings, key: str, *, limit: int, window_seconds: int) -> bool:
        if limit <= 0:
            return True
        client = self._client(settings)
        window = max(1, int(window_seconds))
        redis_key = f"{settings.redis_namespace.strip(':') or 'studyhub-fastapi'}:rate-limit:{key}"
        member = f"{time():.9f}:{secrets.token_hex(4)}"
        result = client.eval(self._CHECK_SCRIPT, 1, redis_key, time(), window, int(limit), member)
        return int(result) == 1

    def _client(self, settings: Settings):
        if self._redis_client is not None:
            return self._redis_client
        if not settings.redis_url:
            raise RuntimeError("Redis rate limit backend requires redis_url")
        import redis  # type: ignore[import-not-found]

        self._redis_client = redis.Redis.from_url(
            settings.redis_url,
            socket_timeout=settings.redis_socket_timeout_seconds,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
        )
        return self._redis_client


_RATE_LIMITER = InMemoryRateLimiter()
_REDIS_RATE_LIMITER = RedisRateLimiter()


def get_rate_limiter() -> InMemoryRateLimiter:
    return _RATE_LIMITER


def get_redis_rate_limiter() -> RedisRateLimiter:
    return _REDIS_RATE_LIMITER


def _rate_limit_backend(settings: Settings) -> str:
    backend = (settings.rate_limit_backend or "auto").strip().lower()
    if backend == "auto":
        return "redis" if settings.redis_url else "local"
    if backend == "redis" and not settings.redis_url:
        return "local"
    return backend if backend in {"local", "redis"} else "local"


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


def client_key_for_request(settings: Settings, request: Request) -> str:
    return _client_key(settings, request)


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
    allowed = rate_limit_key_allowed(
        settings,
        key,
        limit=rule.limit,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if allowed:
        return True, None
    return False, f"Too many {rule.name} requests"


def rate_limit_key_allowed(settings: Settings, key: str, *, limit: int, window_seconds: int) -> bool:
    if _rate_limit_backend(settings) == "redis":
        try:
            return get_redis_rate_limiter().check(
                settings,
                key,
                limit=limit,
                window_seconds=window_seconds,
            )
        except Exception:
            return get_rate_limiter().check(key, limit=limit, window_seconds=window_seconds)
    return get_rate_limiter().check(key, limit=limit, window_seconds=window_seconds)
