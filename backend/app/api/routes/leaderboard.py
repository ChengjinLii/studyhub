from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_leaderboard_read_service, get_public_read_cache
from app.core.db import get_db_session
from app.core.public_read_cache import PublicReadCache
from app.core.response import api_ok
from app.services.leaderboard_read_service import LeaderboardReadService
from sqlalchemy.orm import Session


router = APIRouter(tags=["leaderboard"])


@router.get("/api/leaderboard/contributors")
def contributors(
    limit: int = 8,
    period: str = "all",
    session: Session = Depends(get_db_session),
    cache: PublicReadCache = Depends(get_public_read_cache),
    service: LeaderboardReadService = Depends(get_leaderboard_read_service),
) -> dict[str, object]:
    data = cache.get_or_set(
        "leaderboard:contributors",
        (limit, period),
        lambda: service.get_contributors(session=session, limit=limit, period=period),
    )
    return api_ok(data)
