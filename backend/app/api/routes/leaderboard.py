from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_legacy_leaderboard_read_service, get_leaderboard_read_service
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.response import api_ok
from app.services.legacy_leaderboard_read_service import LegacyLeaderboardReadService
from app.services.leaderboard_read_service import LeaderboardReadService
from sqlalchemy.orm import Session


router = APIRouter(tags=["leaderboard"])


@router.get("/api/leaderboard/contributors")
def contributors(
    limit: int = 8,
    period: str = "all",
    session: Session = Depends(get_db_session),
    legacy_service: LegacyLeaderboardReadService = Depends(get_legacy_leaderboard_read_service),
    service: LeaderboardReadService = Depends(get_leaderboard_read_service),
) -> dict[str, object]:
    settings = get_settings()
    if settings.requires_private_env_file:
        return api_ok(legacy_service.get_contributors(session=session, limit=limit, period=period))
    return api_ok(service.get_contributors(limit=limit, period=period))
