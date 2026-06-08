from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from types import SimpleNamespace

from app.api.deps import (
    get_leaderboard_read_service,
    get_materials_service,
    get_optional_auth_context,
    get_public_read_cache,
)
from app.api.routes import materials as material_routes
from app.core.public_read_cache import PublicReadCache, cache_if_anonymous, invalidate_prefixes
from app.core.observability import get_runtime_metrics
from app.core.security import AuthContext


def _build_cache(*, ttl_seconds: int = 30) -> PublicReadCache:
    return PublicReadCache(
        SimpleNamespace(
            public_read_cache_enabled=True,
            public_read_cache_backend="local",
            public_read_cache_prefix="public-read-cache",
            public_read_cache_ttl_seconds=ttl_seconds,
            public_read_cache_max_entries=128,
            redis_namespace="studyhub-fastapi",
            redis_url=None,
            redis_socket_timeout_seconds=5,
            redis_connect_timeout_seconds=5,
        )
    )


def test_public_read_cache_reuses_anonymous_value() -> None:
    get_runtime_metrics().clear()
    cache = _build_cache()
    calls = 0

    def factory() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": calls}

    first = cache.get_or_set("materials:list", ("page", 1), factory)
    second = cache.get_or_set("materials:list", ("page", 1), factory)

    assert first == {"value": 1}
    assert second == {"value": 1}
    assert calls == 1
    metrics = get_runtime_metrics().render_prometheus(SimpleNamespace(app_name="test", environment="test", resolved_build_git_sha="test"))
    assert 'studyhub_cache_events_total{namespace="materials:list",backend="local",event="miss"} 1' in metrics
    assert 'studyhub_cache_events_total{namespace="materials:list",backend="local",event="hit"} 1' in metrics
    assert 'studyhub_cache_events_total{namespace="materials:list",backend="local",event="set"} 1' in metrics


def test_public_read_cache_singleflight_coalesces_parallel_requests() -> None:
    cache = _build_cache()
    entered = 0
    factory_started = Event()
    release_factory = Event()

    def factory() -> dict[str, int]:
        nonlocal entered
        entered += 1
        factory_started.set()
        release_factory.wait(timeout=2)
        return {"value": 1}

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(cache.get_or_set, "materials:list", ("page", 1), factory)
        assert factory_started.wait(timeout=1)
        second = executor.submit(cache.get_or_set, "materials:list", ("page", 1), factory)
        time.sleep(0.05)
        release_factory.set()

    assert first.result() == {"value": 1}
    assert second.result() == {"value": 1}
    assert entered == 1


def test_cache_if_anonymous_bypasses_authenticated_requests() -> None:
    cache = _build_cache()
    calls = 0

    def factory() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": calls}

    first = cache_if_anonymous(
        cache,
        current_user_id=42,
        namespace="materials:detail",
        key=(1,),
        factory=factory,
    )
    second = cache_if_anonymous(
        cache,
        current_user_id=42,
        namespace="materials:detail",
        key=(1,),
        factory=factory,
    )

    assert first == {"value": 1}
    assert second == {"value": 2}
    assert calls == 2


def test_invalidate_prefixes_evicts_matching_namespaces() -> None:
    get_runtime_metrics().clear()
    cache = _build_cache()

    cache.get_or_set("materials:list", ("page", 1), lambda: {"kind": "materials"})
    cache.get_or_set("market:list", ("page", 1), lambda: {"kind": "market"})

    invalidate_prefixes(cache, "materials")

    assert ("materials:list", ("page", 1)) not in cache._entries
    assert ("market:list", ("page", 1)) in cache._entries
    metrics = get_runtime_metrics().render_prometheus(SimpleNamespace(app_name="test", environment="test", resolved_build_git_sha="test"))
    assert 'studyhub_cache_events_total{namespace="materials",backend="local",event="invalidate"} 1' in metrics


def test_material_view_invalidation_preserves_list_caches(monkeypatch) -> None:
    cache = _build_cache()
    cache.get_or_set("materials:list", ("page", 1), lambda: {"kind": "list"})
    cache.get_or_set("materials:recommendations", ("limit", 6), lambda: {"kind": "recommendations"})
    cache.get_or_set("materials:detail", (101,), lambda: {"kind": "detail"})
    cache.get_or_set("leaderboard:contributors", ("all", 6), lambda: {"kind": "leaderboard"})
    monkeypatch.setattr(material_routes, "get_public_read_cache", lambda: cache)

    material_routes._invalidate_material_detail_caches()

    assert ("materials:list", ("page", 1)) in cache._entries
    assert ("materials:recommendations", ("limit", 6)) in cache._entries
    assert ("leaderboard:contributors", ("all", 6)) in cache._entries
    assert ("materials:detail", (101,)) not in cache._entries


def test_material_download_invalidation_preserves_material_list_caches(monkeypatch) -> None:
    cache = _build_cache()
    cache.get_or_set("materials:list", ("page", 1), lambda: {"kind": "list"})
    cache.get_or_set("materials:recommendations", ("limit", 6), lambda: {"kind": "recommendations"})
    cache.get_or_set("materials:detail", (101,), lambda: {"kind": "detail"})
    cache.get_or_set("leaderboard:contributors", ("all", 6), lambda: {"kind": "leaderboard"})
    monkeypatch.setattr(material_routes, "get_public_read_cache", lambda: cache)

    material_routes._invalidate_material_download_caches()

    assert ("materials:list", ("page", 1)) in cache._entries
    assert ("materials:recommendations", ("limit", 6)) in cache._entries
    assert ("materials:detail", (101,)) not in cache._entries
    assert ("leaderboard:contributors", ("all", 6)) not in cache._entries


def test_public_read_cache_supports_redis_backend(monkeypatch) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.store: dict[str, bytes] = {}

        def get(self, key: str):
            return self.store.get(key)

        def set(self, key: str, value: bytes, ex: int | None = None):
            del ex
            self.store[key] = value
            return True

        def scan_iter(self, match: str, count: int = 0):
            del count
            prefix = match.rstrip("*")
            for key in list(self.store):
                if key.startswith(prefix):
                    yield key

        def delete(self, *keys: str):
            for key in keys:
                self.store.pop(key, None)

    cache = PublicReadCache(
        SimpleNamespace(
            public_read_cache_enabled=True,
            public_read_cache_backend="redis",
            public_read_cache_prefix="public-read-cache",
            public_read_cache_ttl_seconds=30,
            public_read_cache_max_entries=128,
            redis_namespace="studyhub-fastapi",
            redis_url="redis://cache",
            redis_socket_timeout_seconds=5,
            redis_connect_timeout_seconds=5,
        )
    )
    fake_redis = FakeRedis()
    monkeypatch.setattr(cache, "_client", lambda: fake_redis)

    calls = 0

    def factory() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": calls}

    first = cache.get_or_set("materials:list", ("page", 1), factory)
    second = cache.get_or_set("materials:list", ("page", 1), factory)
    cache.invalidate_prefix("materials")
    third = cache.get_or_set("materials:list", ("page", 1), factory)

    assert first == {"value": 1}
    assert second == {"value": 1}
    assert third == {"value": 2}
    assert calls == 2


def test_leaderboard_route_caches_anonymous_reads(client) -> None:
    cache = _build_cache()
    calls = 0

    class FakeLeaderboardService:
        def get_contributors(self, session, limit: int, period: str):
            nonlocal calls
            calls += 1
            return [{"userId": 1, "username": "alice", "downloads": limit, "period": period}]

    client.app.dependency_overrides[get_public_read_cache] = lambda: cache
    client.app.dependency_overrides[get_leaderboard_read_service] = lambda: FakeLeaderboardService()
    try:
        first = client.get("/api/leaderboard/contributors", params={"limit": 6, "period": "all"})
        second = client.get("/api/leaderboard/contributors", params={"limit": 6, "period": "all"})
    finally:
        client.app.dependency_overrides.clear()

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == 1
    assert first.json()["data"] == second.json()["data"]


def test_material_recommendations_skip_cache_for_authenticated_reads(client) -> None:
    cache = _build_cache()
    calls = 0

    class FakeMaterialsService:
        def get_recommendations(self, session, current_user_id: int | None, limit: int | None):
            nonlocal calls
            calls += 1
            return [{"id": calls, "currentUserId": current_user_id, "limit": limit}]

    client.app.dependency_overrides[get_public_read_cache] = lambda: cache
    client.app.dependency_overrides[get_materials_service] = lambda: FakeMaterialsService()
    client.app.dependency_overrides[get_optional_auth_context] = lambda: AuthContext(user_id=7, role_mask=1)
    try:
        first = client.get("/api/materials/recommendations", params={"limit": 4})
        second = client.get("/api/materials/recommendations", params={"limit": 4})
    finally:
        client.app.dependency_overrides.clear()

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == 2
    assert first.json()["data"][0]["currentUserId"] == 7
    assert second.json()["data"][0]["id"] == 2
