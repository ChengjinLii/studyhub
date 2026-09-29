from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.deps import get_finance_repo, get_worker_service
from app.core.config import Settings
from app.core.db import session_scope
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


def test_released_db_lock_is_reclaimable_when_expiry_rounds_forward(client: TestClient) -> None:
    del client
    worker_service = get_worker_service()
    finance_repo = get_finance_repo()
    lock_name = "studyhub:test-released-lock"

    with session_scope() as session:
        assert worker_service.try_acquire_lock(
            session,
            lock_name=lock_name,
            owner_token="worker-a",
            ttl_seconds=120,
        )
        worker_service.release_lock(session, lock_name=lock_name, owner_token="worker-a")

    # MySQL DATETIME may store a released timestamp slightly ahead of the
    # application clock after fractional-second normalization. No owner still
    # means the row is free and must not block the next worker.
    with session_scope() as session:
        lock = finance_repo.get_worker_lock(session, lock_name)
        assert lock is not None
        assert lock.owner_token is None
        lock.expires_at = datetime.now(UTC) + timedelta(seconds=1)
        finance_repo.save_worker_lock(session, lock)
        session.commit()

    with session_scope() as session:
        assert worker_service.try_acquire_lock(
            session,
            lock_name=lock_name,
            owner_token="worker-b",
            ttl_seconds=120,
        )
        worker_service.release_lock(session, lock_name=lock_name, owner_token="worker-b")
