from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import (
    get_comments_service,
    get_optional_auth_context,
    get_public_read_cache,
    require_auth_context,
)
from app.core.db import get_db_session
from app.core.public_read_cache import PublicReadCache, cache_if_anonymous, invalidate_prefixes
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.comments import CommentCreatePayload, CommentReportPayload, CommentUpdatePayload
from app.services.comments_service import CommentsService


router = APIRouter(tags=["comments"])


@router.get("/api/comments")
def list_comments(
    materialId: int,
    sort: str = "latest",
    page: int = 0,
    size: int = 20,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    cache: PublicReadCache = Depends(get_public_read_cache),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    current_user_id = auth.user_id if auth else None
    data = cache_if_anonymous(
        cache,
        current_user_id=current_user_id,
        namespace="comments:list",
        key=(materialId, sort, page, size),
        factory=lambda: service.list_comments(
            session,
            materialId,
            sort=sort,
            page=page,
            size=size,
            current_user_id=current_user_id,
        ),
    )
    return api_ok(data)


@router.get("/api/comments/{id}/replies")
def comment_replies(
    id: int,
    page: int = 0,
    size: int = 20,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    cache: PublicReadCache = Depends(get_public_read_cache),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    current_user_id = auth.user_id if auth else None
    data = cache_if_anonymous(
        cache,
        current_user_id=current_user_id,
        namespace="comments:replies",
        key=(id, page, size),
        factory=lambda: service.list_replies(session, id, page=page, size=size, current_user_id=current_user_id),
    )
    return api_ok(data)


@router.post("/api/comments")
def create_comment(
    payload: CommentCreatePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    data = service.create(session, payload, auth.user_id or 0)
    _invalidate_comment_read_caches()
    return api_ok(data)


@router.patch("/api/comments/{id}")
def update_comment(
    id: int,
    payload: CommentUpdatePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    can_moderate = bool(auth.role_mask and auth.role_mask & 24)
    data = service.update(session, id, payload, user_id=auth.user_id or 0, can_moderate=can_moderate)
    _invalidate_comment_read_caches()
    return api_ok(data)


@router.delete("/api/comments/{id}")
def delete_comment(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    can_moderate = bool(auth.role_mask and auth.role_mask & 24)
    service.delete(session, id, user_id=auth.user_id or 0, can_moderate=can_moderate)
    _invalidate_comment_read_caches()
    return api_ok({"success": True})


@router.put("/api/comments/{id}/like")
@router.post("/api/comments/{id}/like", include_in_schema=False)
def like_comment(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    like_count = service.like(session, id, auth.user_id or 0)
    _invalidate_comment_read_caches()
    return api_ok({"likeCount": like_count})


@router.delete("/api/comments/{id}/like")
def unlike_comment(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    like_count = service.unlike(session, id, auth.user_id or 0)
    _invalidate_comment_read_caches()
    return api_ok({"likeCount": like_count})


@router.post("/api/comments/{id}/reports")
@router.post("/api/comments/{id}/report", include_in_schema=False)
def report_comment(
    id: int,
    payload: CommentReportPayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    service.report(session, id, auth.user_id or 0, payload)
    _invalidate_comment_read_caches()
    return api_ok({"success": True})


def _invalidate_comment_read_caches() -> None:
    invalidate_prefixes(get_public_read_cache(), "comments", "materials")
