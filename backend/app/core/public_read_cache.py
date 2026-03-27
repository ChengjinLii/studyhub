from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from threading import RLock
from time import monotonic
from typing import Any, Callable, Hashable

from app.core.config import Settings


@dataclass(slots=True)
class _CacheEntry:
    expires_at: float
    value: Any


class PublicReadCache:
    """Cache for anonymous read-heavy endpoints.

    Backend selection is conservative:
    - local in-process cache always works
    - Redis is enabled only when explicitly requested or auto-detected
    - Redis failures fall back to local execution instead of failing requests
    """

    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.public_read_cache_enabled and settings.public_read_cache_ttl_seconds > 0
        self.ttl_seconds = max(1, settings.public_read_cache_ttl_seconds)
        self.max_entries = max(32, settings.public_read_cache_max_entries)
        self.redis_namespace = settings.redis_namespace.strip(":") or "studyhub-fastapi"
        self.redis_prefix = settings.public_read_cache_prefix.strip(":") or "public-read-cache"
        self.redis_url = settings.redis_url
        self.redis_socket_timeout_seconds = settings.redis_socket_timeout_seconds
        self.redis_connect_timeout_seconds = settings.redis_connect_timeout_seconds
        self.backend = self._resolve_backend(settings)
        self._entries: dict[tuple[str, Hashable], _CacheEntry] = {}
        self._lock = RLock()
        self._redis_client: Any | None = None

    def get_or_set(self, namespace: str, key: Hashable, factory: Callable[[], Any]) -> Any:
        if not self.enabled:
            return factory()
        if self.backend == "redis":
            return self._redis_get_or_set(namespace, key, factory)
        return self._local_get_or_set(namespace, key, factory)

    def invalidate_prefix(self, prefix: str) -> None:
        if not self.enabled:
            return
        self._invalidate_local_prefix(prefix)
        if self.backend == "redis":
            self._invalidate_redis_prefix(prefix)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
        if self.backend == "redis":
            self._clear_redis()

    def _resolve_backend(self, settings: Settings) -> str:
        requested = (settings.public_read_cache_backend or "auto").strip().lower()
        if requested == "redis":
            return "redis"
        if requested == "auto" and settings.redis_url:
            return "redis"
        return "local"

    def _local_get_or_set(self, namespace: str, key: Hashable, factory: Callable[[], Any]) -> Any:
        now = monotonic()
        composite_key = (namespace, key)
        with self._lock:
            self._purge_expired_locked(now)
            cached = self._entries.get(composite_key)
            if cached is not None and cached.expires_at > now:
                return cached.value
        value = factory()
        with self._lock:
            self._purge_expired_locked(now)
            self._entries[composite_key] = _CacheEntry(expires_at=now + self.ttl_seconds, value=value)
            self._evict_overflow_locked()
        return value

    def _redis_get_or_set(self, namespace: str, key: Hashable, factory: Callable[[], Any]) -> Any:
        client = self._safe_redis_client()
        if client is None:
            return self._local_get_or_set(namespace, key, factory)
        redis_key = self._redis_key(namespace, key)
        try:
            cached = client.get(redis_key)
            if cached:
                return json.loads(cached.decode("utf-8"))
        except Exception:
            return self._local_get_or_set(namespace, key, factory)
        value = factory()
        try:
            client.set(redis_key, self._serialize_value(value), ex=self.ttl_seconds)
        except Exception:
            return self._local_get_or_set(namespace, key, lambda: value)
        return value

    def _invalidate_local_prefix(self, prefix: str) -> None:
        with self._lock:
            doomed = [key for key in self._entries if key[0].startswith(prefix)]
            for key in doomed:
                self._entries.pop(key, None)

    def _invalidate_redis_prefix(self, prefix: str) -> None:
        client = self._safe_redis_client()
        if client is None:
            return
        pattern = f"{self.redis_namespace}:{self.redis_prefix}:{prefix}*"
        try:
            keys = list(client.scan_iter(match=pattern, count=200))
            if keys:
                client.delete(*keys)
        except Exception:
            return

    def _clear_redis(self) -> None:
        client = self._safe_redis_client()
        if client is None:
            return
        pattern = f"{self.redis_namespace}:{self.redis_prefix}:*"
        try:
            keys = list(client.scan_iter(match=pattern, count=500))
            if keys:
                client.delete(*keys)
        except Exception:
            return

    def _safe_redis_client(self):
        try:
            return self._client()
        except Exception:
            return None

    def _client(self):
        if self._redis_client is not None:
            return self._redis_client
        if not self.redis_url:
            raise RuntimeError("Redis public read cache 缺少 redis_url 配置。")
        import redis  # type: ignore[import-not-found]

        self._redis_client = redis.Redis.from_url(
            self.redis_url,
            socket_timeout=self.redis_socket_timeout_seconds,
            socket_connect_timeout=self.redis_connect_timeout_seconds,
            decode_responses=False,
        )
        return self._redis_client

    def _redis_key(self, namespace: str, key: Hashable) -> str:
        return f"{self.redis_namespace}:{self.redis_prefix}:{namespace}:{self._hash_key(key)}"

    def _hash_key(self, key: Hashable) -> str:
        try:
            serialized = json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            serialized = repr(key)
        return hashlib.sha1(serialized.encode("utf-8")).hexdigest()

    def _serialize_value(self, value: Any) -> bytes:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")

    def _purge_expired_locked(self, now: float) -> None:
        doomed = [key for key, value in self._entries.items() if value.expires_at <= now]
        for key in doomed:
            self._entries.pop(key, None)

    def _evict_overflow_locked(self) -> None:
        while len(self._entries) > self.max_entries:
            oldest_key = next(iter(self._entries))
            self._entries.pop(oldest_key, None)


def cache_if_anonymous(
    cache: PublicReadCache,
    *,
    current_user_id: int | None,
    namespace: str,
    key: Hashable,
    factory: Callable[[], Any],
) -> Any:
    if current_user_id is not None:
        return factory()
    return cache.get_or_set(namespace, key, factory)


def invalidate_prefixes(cache: PublicReadCache, *prefixes: str) -> None:
    for prefix in prefixes:
        cache.invalidate_prefix(prefix)
