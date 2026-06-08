from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.services.market_service import MarketService


class _MappingResult:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def mappings(self):
        return self

    def first(self) -> dict[str, Any]:
        return self.row


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar(self) -> int:
        return self.value


class _StatsSession:
    def __init__(self) -> None:
        self.market_queries = 0
        self.user_queries = 0

    def execute(self, statement, params=None):
        del params
        sql = " ".join(str(statement).lower().split())
        if "from market_items" in sql:
            self.market_queries += 1
            return _MappingResult({"active": 7, "sold": 3})
        if "from users" in sql:
            self.user_queries += 1
            return _ScalarResult(5)
        raise AssertionError(f"unexpected SQL: {statement}")


class _AsyncStatsSession(_StatsSession):
    async def execute(self, statement, params=None):
        return super().execute(statement, params)


def _build_service() -> MarketService:
    fake_settings = SimpleNamespace(
        requires_private_env_file=True,
        async_read_db_enabled=True,
    )
    return MarketService(fake_settings, read_repo=None, auth_repo=None, market_repo=None, asset_store=None)


def test_legacy_market_stats_uses_single_market_items_aggregate_query() -> None:
    service = _build_service()
    session = _StatsSession()

    data = service._compat_load_market_stats(session)  # type: ignore[arg-type]

    assert data == {"active": 7, "sold": 3, "userCount": 5}
    assert session.market_queries == 1
    assert session.user_queries == 1


def test_async_legacy_market_stats_uses_single_market_items_aggregate_query() -> None:
    service = _build_service()
    session = _AsyncStatsSession()

    data = asyncio.run(service._compat_load_market_stats_async(session))

    assert data == {"active": 7, "sold": 3, "userCount": 5}
    assert session.market_queries == 1
    assert session.user_queries == 1


def test_async_legacy_market_list_keeps_page_stats_and_wanted_state(monkeypatch) -> None:
    service = _build_service()
    row = {
        "id": 201,
        "seller_id": 2,
        "seller_username": "baishan",
        "seller_nickname": "白山",
        "title": "微积分教材",
        "price": 2500,
        "category": "BOOK",
        "images_json": "[\"https://img.example/book.png\"]",
        "want_count": 4,
        "school": "电子科技大学",
        "created_at": "2026-01-02T03:04:05Z",
    }
    stats = {"active": 7, "sold": 3, "userCount": 5}

    async def fake_call(loader, *args, **kwargs):
        name = loader.__name__
        if name == "_compat_count_market_rows_async":
            assert kwargs["keyword"] == "教材"
            assert kwargs["category"] == "book"
            return 7
        if name == "_compat_load_market_rows_async":
            assert kwargs["keyword"] == "教材"
            assert kwargs["category"] == "book"
            assert kwargs["limit"] == 10
            assert kwargs["offset"] == 10
            return [row]
        if name == "_compat_load_market_stats_async":
            return stats
        if name == "_compat_load_wanted_ids_async":
            assert args == (12, [201])
            return {201}
        raise AssertionError(f"unexpected loader: {name}")

    monkeypatch.setattr(service, "_call_with_new_async_session", fake_call)

    data = asyncio.run(
        service.list_market_async(
            session=None,
            current_user_id=12,
            keyword="教材",
            category="book",
            page=2,
            size=10,
        )
    )

    assert data["meta"] == {"page": 2, "size": 10, "total": 7}
    assert data["stats"] == stats
    assert data["items"][0]["id"] == 201
    assert data["items"][0]["sellerName"] == "白山"
    assert data["items"][0]["wanted"] is True
    assert data["items"][0]["thumbnail"] == "https://img.example/book.png"
    assert data["items"][0]["thumbnailVariant"] == {
        "src": "https://img.example/book.png",
        "srcSet": None,
        "webpSrcSet": None,
        "avifSrcSet": None,
        "lqip": None,
    }
