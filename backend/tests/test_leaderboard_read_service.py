from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.services.leaderboard_read_service import LeaderboardReadService


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
        assert params == {"limit": 6}
        self.queries += 1
        return _RowsResult(
            [
                {"user_id": 2, "username": "baishan", "downloads": 128, "role_mask": 2},
                {"user_id": 1, "username": "alice", "downloads": 84, "role_mask": 1},
            ]
        )


class _AsyncLeaderboardSession(_LeaderboardSession):
    async def execute(self, statement, params=None):
        return super().execute(statement, params)


class _SeedRepo:
    def __init__(self) -> None:
        self.loads = 0

    def load_seed(self) -> dict[str, Any]:
        self.loads += 1
        return {
            "leaderboard": {
                "all": [
                    {"userId": 2, "username": "baishan", "downloads": 128, "roleMask": 2},
                    {"userId": 1, "username": "alice", "downloads": 84, "roleMask": 1},
                ]
            }
        }


def _build_service(*, requires_private_env_file: bool) -> LeaderboardReadService:
    settings = SimpleNamespace(
        requires_private_env_file=requires_private_env_file,
        async_read_db_enabled=True,
        public_read_cache_ttl_seconds=30,
    )
    return LeaderboardReadService(settings, _SeedRepo())  # type: ignore[arg-type]


def test_seed_contributor_leaderboard_cache_reuses_seed_until_invalidated() -> None:
    repo = _SeedRepo()
    settings = SimpleNamespace(requires_private_env_file=False, public_read_cache_ttl_seconds=30)
    service = LeaderboardReadService(settings, repo)  # type: ignore[arg-type]

    first = service.get_contributors(session=None, limit=6, period="all")  # type: ignore[arg-type]
    first[0]["downloads"] = 999
    second = service.get_contributors(session=None, limit=6, period="all")  # type: ignore[arg-type]

    assert second[0]["downloads"] == 128
    assert repo.loads == 1

    service.invalidate_contributor_cache()
    service.get_contributors(session=None, limit=6, period="all")  # type: ignore[arg-type]

    assert repo.loads == 2


def test_compat_contributor_leaderboard_cache_reuses_query_until_invalidated() -> None:
    service = _build_service(requires_private_env_file=True)
    session = _LeaderboardSession()

    first = service.get_contributors(session=session, limit=6, period="all")  # type: ignore[arg-type]
    first.append({"userId": 99, "username": "polluted", "downloads": 1, "roleMask": 1})
    second = service.get_contributors(session=session, limit=6, period="all")  # type: ignore[arg-type]

    assert [row["userId"] for row in second] == [2, 1]
    assert session.queries == 1

    service.invalidate_contributor_cache()
    service.get_contributors(session=session, limit=6, period="all")  # type: ignore[arg-type]

    assert session.queries == 2


def test_async_compat_contributor_leaderboard_cache_reuses_query() -> None:
    service = _build_service(requires_private_env_file=True)
    session = _AsyncLeaderboardSession()

    first = asyncio.run(service._compat_get_contributors_async(session, limit=6, period="all"))
    second = asyncio.run(service._compat_get_contributors_async(session, limit=6, period="all"))

    assert first == second
    assert session.queries == 1
