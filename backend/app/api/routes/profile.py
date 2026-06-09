from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_user_follow_service, get_user_read_service, require_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.services.user_follow_service import UserFollowService
from app.services.user_read_service import UserReadService


router = APIRouter(tags=["profile"])


@router.get("/api/me")
async def profile_overview(
    auth: AuthContext = Depends(require_auth_context),
    service: UserReadService = Depends(get_user_read_service),
) -> dict[str, object]:
    return api_ok(await service.get_overview_async(auth.user_id or 0))


@router.get("/api/users/{id}/profile")
async def user_profile(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    service: UserReadService = Depends(get_user_read_service),
) -> dict[str, object]:
    return api_ok(await service.get_public_profile_async(auth.user_id or 0, auth.role_mask, id))


@router.get("/api/users/{id}/uploads")
def user_uploads(
    id: int,
    limit: int | None = None,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: UserReadService = Depends(get_user_read_service),
) -> dict[str, object]:
    return api_ok(service.get_user_uploads(session, auth.user_id or 0, id, auth.role_mask, limit))


@router.get("/api/users/{id}/market")
def user_market_listings(
    id: int,
    limit: int | None = None,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: UserReadService = Depends(get_user_read_service),
) -> dict[str, object]:
    return api_ok(service.get_user_market_listings(session, auth.user_id or 0, id, auth.role_mask, limit))


@router.get("/api/users/{id}/followers")
def user_followers(
    id: int,
    _: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: UserFollowService = Depends(get_user_follow_service),
) -> dict[str, object]:
    return api_ok(service.list_followers(session, id))


@router.get("/api/users/{id}/following")
def user_following(
    id: int,
    _: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: UserFollowService = Depends(get_user_follow_service),
) -> dict[str, object]:
    return api_ok(service.list_following(session, id))


@router.put("/api/users/{id}/follow")
@router.post("/api/users/{id}/follow")
def follow_user(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: UserFollowService = Depends(get_user_follow_service),
) -> dict[str, object]:
    service.follow(session, follower_id=auth.user_id or 0, target_user_id=id)
    return api_ok()


@router.delete("/api/users/{id}/follow")
def unfollow_user(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: UserFollowService = Depends(get_user_follow_service),
) -> dict[str, object]:
    service.unfollow(session, follower_id=auth.user_id or 0, target_user_id=id)
    return api_ok()
