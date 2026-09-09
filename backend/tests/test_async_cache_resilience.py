import asyncio
from types import SimpleNamespace

import pytest

from app.core.public_read_cache import PublicReadCache


class FakeRedis:
    def __init__(self, fail_set=False):
        self.values = {}
        self.fail_set = fail_set

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, *, ex):
        if self.fail_set:
            raise ConnectionError("injected failure")
        self.values[key] = value


def cache_for(backend, fail_set=False):
    cache = PublicReadCache(SimpleNamespace(
        public_read_cache_enabled=True, public_read_cache_backend=backend,
        public_read_cache_prefix="test", public_read_cache_ttl_seconds=30,
        public_read_cache_max_entries=32, redis_namespace="test", redis_url=None,
        redis_socket_timeout_seconds=.1, redis_connect_timeout_seconds=.1,
    ))
    fake = FakeRedis(fail_set)
    cache._safe_redis_client = lambda: fake
    return cache


@pytest.mark.parametrize("backend", ["local", "redis"])
def test_cancelled_producer_releases_followers(backend):
    async def scenario():
        cache = cache_for(backend)
        started = asyncio.Event()

        async def produce():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(cache.get_or_set_async("n", "k", produce))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not cache._async_inflight
        assert await asyncio.wait_for(cache.get_or_set_async("n", "k", lambda: 42), 1) == 42

    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["local", "redis"])
def test_followers_coalesce_and_cancellation_does_not_remove_owner(backend):
    async def scenario():
        cache = cache_for(backend)
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def produce():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return 42

        owner = asyncio.create_task(cache.get_or_set_async("n", "k", produce))
        await started.wait()
        follower = asyncio.create_task(cache.get_or_set_async("n", "k", produce))
        await asyncio.sleep(.02)
        follower.cancel()
        with pytest.raises(asyncio.CancelledError):
            await follower
        assert ("n", "k") in cache._async_inflight
        others = [asyncio.create_task(cache.get_or_set_async("n", "k", produce)) for _ in range(5)]
        release.set()
        assert await asyncio.wait_for(asyncio.gather(owner, *others), 1) == [42] * 6
        assert calls == 1
        assert not cache._async_inflight

    asyncio.run(scenario())


def test_redis_set_failure_returns_completed_value_without_self_wait():
    async def scenario():
        cache = cache_for("redis", fail_set=True)
        assert await asyncio.wait_for(cache.get_or_set_async("n", "k", lambda: 42), 1) == 42
        assert cache._entries[("n", "k")].value == 42
        assert not cache._async_inflight
    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["local", "redis"])
def test_failed_factory_can_be_retried(backend):
    async def scenario():
        cache = cache_for(backend)
        def fail():
            raise ValueError("injected failure")
        with pytest.raises(ValueError):
            await cache.get_or_set_async("n", "k", fail)
        assert not cache._async_inflight
        assert await cache.get_or_set_async("n", "k", lambda: 42) == 42
    asyncio.run(scenario())


def test_wait_timeout_does_not_start_duplicate_factory():
    async def scenario():
        cache = cache_for("local")
        cache.ttl_seconds = .03
        started, release = asyncio.Event(), asyncio.Event()
        async def produce():
            started.set()
            await release.wait()
            return 42
        owner = asyncio.create_task(cache.get_or_set_async("n", "k", produce))
        await started.wait()
        try:
            with pytest.raises(TimeoutError):
                await cache.get_or_set_async("n", "k", lambda: pytest.fail("duplicate factory"))
            assert ("n", "k") in cache._async_inflight
        finally:
            release.set()
            await owner
    asyncio.run(scenario())
