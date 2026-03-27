from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_leaderboard_read_service
from app.core.response import api_ok
from app.services.leaderboard_read_service import LeaderboardReadService


router = APIRouter(tags=["leaderboard"])


@router.get("/api/leaderboard/contributors")
def contributors(
    limit: int = 8,
    period: str = "all",
    service: LeaderboardReadService = Depends(get_leaderboard_read_service),
) -> dict[str, object]:
    return api_ok(service.get_contributors(limit=limit, period=period))
