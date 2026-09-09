from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.config import Settings
from app.core.rate_limit import InMemoryRateLimiter, RedisRateLimiter


def test_local_fallback_is_atomic_across_threads():
    limiter = InMemoryRateLimiter()
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: limiter.check("same", limit=6, window_seconds=60), range(100)))
    assert sum(results) == 6


def test_redis_failure_opens_circuit_and_recovers(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.core.rate_limit.monotonic", lambda: now[0])
    limiter = RedisRateLimiter()

    class Client:
        calls = 0

        def eval(self, *args):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("offline")
            return 1

    client = Client()
    limiter._redis_client = client
    settings = Settings()
    for _ in range(3):
        with pytest.raises(ConnectionError):
            limiter.check(settings, "key", limit=10, window_seconds=60)
    assert client.calls == 1
    now[0] += 6
    assert limiter.check(settings, "key", limit=10, window_seconds=60)
    assert client.calls == 2
