from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.services.requests_service import RequestsService


class _RowsResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self):
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class _LeaderboardSession:
    def __init__(self) -> None:
        self.queries = 0

    def execute(self, statement, params=None):
        del statement
        assert params == {"max_amount": 50000, "limit": 6}
        self.queries += 1
        return _RowsResult([_request_row(501)])


class _AsyncLeaderboardSession(_LeaderboardSession):
    async def execute(self, statement, params=None):
        return super().execute(statement, params)


def _build_service() -> RequestsService:
    fake_settings = SimpleNamespace(
        requires_private_env_file=True,
        async_read_db_enabled=True,
        public_read_cache_ttl_seconds=30,
    )
    return RequestsService(fake_settings, read_repo=None, auth_repo=None, material_repo=None, request_repo=None)


def _request_row(request_id: int, *, requester_id: int = 2, response_count: int = 0, anonymous: bool = False) -> dict[str, object]:
    return {
        "id": request_id,
        "requester_id": requester_id,
        "course": "概率论",
        "keyword": "期末真题",
        "school": "电子科技大学",
        "college": "信通",
        "major": "通信",
        "budget": 2000,
        "funded_amount": 1500,
        "contribution_count": 2,
        "deadline": "WEEK",
        "urgency_tier": "WEEK",
        "creator_floor": 1000,
        "preview_requirement": "先看目录",
        "anonymous": anonymous,
        "response_count": response_count,
        "accepted_response_id": None,
        "status": "OPEN",
        "created_at": "2026-01-02T03:04:05Z",
        "requester_username": "baishan",
        "requester_nickname": "白山",
    }


def test_async_legacy_request_list_keeps_sort_filter_and_responded_state(monkeypatch) -> None:
    service = _build_service()
    rows = [
        _request_row(401, response_count=3),
        _request_row(402, response_count=9),
    ]

    async def fake_call(loader, *args, **kwargs):
        del kwargs
        name = loader.__name__
        if name == "_compat_load_open_requests_async":
            return rows
        if name == "_compat_load_viewer_profile_async":
            assert args == (12,)
            return {"school": "电子科技大学", "college": "信通", "major": "通信"}
        if name == "_compat_load_hidden_early_exit_request_ids_async":
            assert args == ([401, 402],)
            return {402}
        if name == "_compat_load_responded_request_ids_async":
            assert args == (12, [401])
            return {401}
        raise AssertionError(f"unexpected loader: {name}")

    monkeypatch.setattr(service, "_call_with_new_async_session", fake_call)

    data = asyncio.run(service.list_requests_async(session=None, viewer_id=12, sort="hot", limit=5))

    assert [item["id"] for item in data] == [401]
    assert data[0]["requesterName"] == "白山"
    assert data[0]["responded"] is True
    assert data[0]["owner"] is False
    assert data[0]["budget"] == 20.0


def test_async_legacy_request_list_skips_user_state_loads_for_anonymous_reads(monkeypatch) -> None:
    service = _build_service()
    row = _request_row(401, response_count=3)

    async def fake_call(loader, *args, **kwargs):
        del args, kwargs
        name = loader.__name__
        if name == "_compat_load_open_requests_async":
            return [row]
        if name == "_compat_load_hidden_early_exit_request_ids_async":
            return set()
        if name in {"_compat_load_viewer_profile_async", "_compat_load_responded_request_ids_async"}:
            raise AssertionError("anonymous request list should not load user state")
        raise AssertionError(f"unexpected loader: {name}")

    monkeypatch.setattr(service, "_call_with_new_async_session", fake_call)

    data = asyncio.run(service.list_requests_async(session=None, viewer_id=None, sort="hot", limit=5))

    assert [item["id"] for item in data] == [401]
    assert data[0]["responded"] is False
    assert data[0]["owner"] is False


def test_async_legacy_request_list_applies_offset_after_sorting(monkeypatch) -> None:
    service = _build_service()
    rows = [
        _request_row(401, response_count=9),
        _request_row(402, response_count=6),
        _request_row(403, response_count=3),
    ]

    async def fake_call(loader, *args, **kwargs):
        del args, kwargs
        name = loader.__name__
        if name == "_compat_load_open_requests_async":
            return rows
        if name == "_compat_load_hidden_early_exit_request_ids_async":
            return set()
        raise AssertionError(f"unexpected loader: {name}")

    monkeypatch.setattr(service, "_call_with_new_async_session", fake_call)

    data = asyncio.run(service.list_requests_async(session=None, viewer_id=None, sort="hot", limit=1, offset=1))

    assert [item["id"] for item in data] == [402]


def test_async_legacy_request_leaderboard_keeps_limit_and_responded_state(monkeypatch) -> None:
    service = _build_service()
    row = _request_row(501, requester_id=12, response_count=4, anonymous=True)

    async def fake_call(loader, *args, **kwargs):
        del kwargs
        name = loader.__name__
        if name == "_compat_load_leaderboard_rows_async":
            assert args == (50,)
            return [row]
        if name == "_compat_load_hidden_early_exit_request_ids_async":
            assert args == ([501],)
            return set()
        if name == "_compat_load_responded_request_ids_async":
            assert args == (12, [501])
            return {501}
        raise AssertionError(f"unexpected loader: {name}")

    monkeypatch.setattr(service, "_call_with_new_async_session", fake_call)

    data = asyncio.run(service.list_leaderboard_async(session=None, viewer_id=12, limit=99))

    assert [item["id"] for item in data] == [501]
    assert data[0]["requesterName"] == "白山"
    assert data[0]["owner"] is True
    assert data[0]["responded"] is True


def test_async_legacy_request_leaderboard_skips_responded_load_for_anonymous_reads(monkeypatch) -> None:
    service = _build_service()
    row = _request_row(501, requester_id=12, response_count=4, anonymous=True)

    async def fake_call(loader, *args, **kwargs):
        del kwargs
        name = loader.__name__
        if name == "_compat_load_leaderboard_rows_async":
            assert args == (10,)
            return [row]
        if name == "_compat_load_hidden_early_exit_request_ids_async":
            assert args == ([501],)
            return set()
        if name == "_compat_load_responded_request_ids_async":
            raise AssertionError("anonymous request leaderboard should not load responded ids")
        raise AssertionError(f"unexpected loader: {name}")

    monkeypatch.setattr(service, "_call_with_new_async_session", fake_call)

    data = asyncio.run(service.list_leaderboard_async(session=None, viewer_id=None, limit=10))

    assert [item["id"] for item in data] == [501]
    assert data[0]["owner"] is False
    assert data[0]["responded"] is False


def test_compat_request_leaderboard_cache_reuses_query_until_invalidated() -> None:
    service = _build_service()
    session = _LeaderboardSession()

    first = service._compat_load_leaderboard_rows(session, 6)
    first[0]["id"] = 999
    second = service._compat_load_leaderboard_rows(session, 6)

    assert second[0]["id"] == 501
    assert session.queries == 1

    service.invalidate_request_read_cache()
    service._compat_load_leaderboard_rows(session, 6)

    assert session.queries == 2


def test_async_compat_request_leaderboard_cache_reuses_query_until_invalidated() -> None:
    service = _build_service()
    session = _AsyncLeaderboardSession()

    first = asyncio.run(service._compat_load_leaderboard_rows_async(session, 6))
    first[0]["id"] = 999
    second = asyncio.run(service._compat_load_leaderboard_rows_async(session, 6))

    assert second[0]["id"] == 501
    assert session.queries == 1

    service.invalidate_request_read_cache()
    asyncio.run(service._compat_load_leaderboard_rows_async(session, 6))

    assert session.queries == 2
