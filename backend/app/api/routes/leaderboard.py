from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_leaderboard_read_service, get_public_read_cache
from app.core.db import get_db_session
from app.core.public_read_cache import PublicReadCache, cache_if_anonymous_async
from app.core.response import api_ok
from app.services.leaderboard_read_service import LeaderboardReadService
from sqlalchemy.orm import Session


router = APIRouter(tags=["leaderboard"])


def _call_service_method(service, async_name: str, sync_name: str, *args, **kwargs):
    method = getattr(service, async_name, None)
    if method is not None:
        return method(*args, **kwargs)
    return getattr(service, sync_name)(*args, **kwargs)


@router.get("/api/leaderboard/contributors")
async def contributors(
    limit: int = 8,
    period: str = "all",
    session: Session = Depends(get_db_session),
    cache: PublicReadCache = Depends(get_public_read_cache),
    service: LeaderboardReadService = Depends(get_leaderboard_read_service),
) -> dict[str, object]:
    data = await cache_if_anonymous_async(
        cache,
        current_user_id=None,
        namespace="leaderboard:contributors",
        key=(limit, period),
        factory=lambda: _call_service_method(
            service,
            "get_contributors_async",
            "get_contributors",
            session=session,
            limit=limit,
            period=period,
        ),
    )
    return api_ok(data)
