from __future__ import annotations

from typing import Any

from app.core.config import Settings


def create_redis_client(settings: Settings, *, decode_responses: bool = False) -> Any:
    if not settings.redis_url:
        raise RuntimeError("Redis URL is not configured")
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(
        settings.redis_url,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_connect_timeout_seconds,
        health_check_interval=30,
        max_connections=32,
        retry_on_timeout=False,
        decode_responses=decode_responses,
        client_name=f"studyhub-{settings.environment.strip().lower() or 'runtime'}",
    )


def redis_namespace(settings: Settings) -> str:
    return settings.redis_namespace.strip(":") or "studyhub-fastapi"
