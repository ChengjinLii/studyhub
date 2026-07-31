from __future__ import annotations

from app.core.config import Settings
from app.providers.lock import RedisLockProvider


class _RedisPipeline:
    def __init__(self, client: "_RedisClient") -> None:
        self.client = client
        self.key: str | None = None
        self.operation: tuple[str, int | None] | None = None

    def __enter__(self) -> "_RedisPipeline":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.reset()

    def watch(self, key: str) -> None:
        self.key = key

    def get(self, key: str) -> bytes | None:
        value = self.client.values.get(key)
        return value.encode("utf-8") if value is not None else None

    def unwatch(self) -> None:
        self.key = None

    def multi(self) -> None:
        return None

    def expire(self, key: str, ttl_seconds: int) -> None:
        assert key == self.key
        self.operation = ("expire", ttl_seconds)

    def delete(self, key: str) -> None:
        assert key == self.key
        self.operation = ("delete", None)

    def execute(self) -> list[int]:
        assert self.key is not None and self.operation is not None
        operation, ttl_seconds = self.operation
        if operation == "expire":
            if self.key not in self.client.values:
                return [0]
            assert ttl_seconds is not None
            self.client.ttls[self.key] = ttl_seconds
            return [1]
        existed = int(self.key in self.client.values)
        self.client.values.pop(self.key, None)
        self.client.ttls.pop(self.key, None)
        return [existed]

    def reset(self) -> None:
        self.key = None
        self.operation = None


class _RedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def pipeline(self) -> _RedisPipeline:
        return _RedisPipeline(self)


def test_redis_lock_renewal_and_release_require_the_current_owner(monkeypatch) -> None:
    client = _RedisClient()
    provider = RedisLockProvider(Settings(redis_url="redis://127.0.0.1:6379/15"))
    monkeypatch.setattr(provider, "_client", lambda: client)
    key = provider._key("agent-execution:run-1")

    assert provider.acquire(None, lock_name="agent-execution:run-1", owner_token="worker-a", ttl_seconds=30)
    assert provider.acquire(None, lock_name="agent-execution:run-1", owner_token="worker-b", ttl_seconds=30) is False
    assert provider.renew(None, lock_name="agent-execution:run-1", owner_token="worker-a", ttl_seconds=60)
    assert client.ttls[key] == 60

    provider.release(None, lock_name="agent-execution:run-1", owner_token="worker-b")
    assert client.values[key] == "worker-a"
    provider.release(None, lock_name="agent-execution:run-1", owner_token="worker-a")
    assert key not in client.values
