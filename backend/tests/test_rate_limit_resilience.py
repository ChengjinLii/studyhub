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


def test_local_fallback_has_bounded_key_cardinality():
    limiter = InMemoryRateLimiter(max_entries=128)

    results = [limiter.check(f"client-{index}", limit=10, window_seconds=60) for index in range(200)]

    assert sum(results) == 128
    assert len(limiter._hits) == 128


def test_short_window_cleanup_does_not_drop_long_window_counters(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.core.rate_limit.monotonic", lambda: now[0])
    limiter = InMemoryRateLimiter(max_entries=128)
    for index in range(128):
        assert limiter.check(f"hour-{index}", limit=10, window_seconds=3600)

    now[0] += 120
    assert not limiter.check("new-minute-client", limit=10, window_seconds=60)
    assert len(limiter._hits) == 128

    now[0] += 3600
    assert limiter.check("new-minute-client", limit=10, window_seconds=60)
