from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import (
    get_comments_service,
    get_optional_auth_context,
    require_auth_context,
)
from app.core.db import get_db_session
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
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    return api_ok(
        service.list_comments(session, materialId, sort=sort, page=page, size=size, current_user_id=auth.user_id if auth else None)
    )


@router.get("/api/comments/{id}/replies")
def comment_replies(
    id: int,
    page: int = 0,
    size: int = 20,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    return api_ok(service.list_replies(session, id, page=page, size=size, current_user_id=auth.user_id if auth else None))


@router.post("/api/comments")
def create_comment(
    payload: CommentCreatePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    return api_ok(service.create(session, payload, auth.user_id or 0))


@router.patch("/api/comments/{id}")
def update_comment(
    id: int,
    payload: CommentUpdatePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    can_moderate = bool(auth.role_mask and auth.role_mask & 24)
    return api_ok(service.update(session, id, payload, user_id=auth.user_id or 0, can_moderate=can_moderate))


@router.delete("/api/comments/{id}")
def delete_comment(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    can_moderate = bool(auth.role_mask and auth.role_mask & 24)
    service.delete(session, id, user_id=auth.user_id or 0, can_moderate=can_moderate)
    return api_ok({"success": True})


@router.post("/api/comments/{id}/like")
def like_comment(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    return api_ok({"likeCount": service.like(session, id, auth.user_id or 0)})


@router.delete("/api/comments/{id}/like")
def unlike_comment(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    return api_ok({"likeCount": service.unlike(session, id, auth.user_id or 0)})


@router.post("/api/comments/{id}/report")
def report_comment(
    id: int,
    payload: CommentReportPayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: CommentsService = Depends(get_comments_service),
) -> dict[str, object]:
    service.report(session, id, auth.user_id or 0, payload)
    return api_ok({"success": True})
