from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_community_service, get_optional_auth_context, require_privileged_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.community import FeedbackPayload, UpdateStatusPayload, VolunteerPayload
from app.services.community_service import CommunityService


router = APIRouter(tags=["community"])


@router.post("/api/feedback")
def submit_feedback(
    payload: FeedbackPayload,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    service: CommunityService = Depends(get_community_service),
) -> dict[str, object]:
    return api_ok(service.submit_feedback(session, payload, auth.user_id if auth else None))


@router.post("/api/volunteers")
def submit_volunteer(
    payload: VolunteerPayload,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    service: CommunityService = Depends(get_community_service),
) -> dict[str, object]:
    return api_ok(service.submit_volunteer(session, payload, auth.user_id if auth else None))


@router.get("/api/admin/community/feedbacks")
@router.get("/api/admin/feedbacks")
def list_feedbacks_for_admin(
    type: str | None = None,
    status: str | None = None,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: CommunityService = Depends(get_community_service),
) -> dict[str, object]:
    return api_ok(service.list_feedbacks(session, type, status))


@router.patch("/api/admin/community/feedbacks/{id}")
@router.patch("/api/admin/feedbacks/{id}")
def update_feedback_status_for_admin(
    id: int,
    payload: UpdateStatusPayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: CommunityService = Depends(get_community_service),
) -> dict[str, object]:
    return api_ok(service.update_feedback_status(session, id, payload))


@router.patch("/api/admin/feedbacks", include_in_schema=False)
def update_feedback_status_for_admin_alias(
    payload: UpdateStatusPayload,
    id: int = Query(..., ge=1),
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: CommunityService = Depends(get_community_service),
) -> dict[str, object]:
    return api_ok(service.update_feedback_status(session, id, payload))


@router.get("/api/admin/community/volunteers")
@router.get("/api/admin/volunteers")
def list_volunteers_for_admin(
    status: str | None = None,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: CommunityService = Depends(get_community_service),
) -> dict[str, object]:
    return api_ok(service.list_volunteers(session, status))


@router.patch("/api/admin/community/volunteers/{id}")
@router.patch("/api/admin/volunteers/{id}")
def update_volunteer_status_for_admin(
    id: int,
    payload: UpdateStatusPayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: CommunityService = Depends(get_community_service),
) -> dict[str, object]:
    return api_ok(service.update_volunteer_status(session, id, payload))


@router.patch("/api/admin/volunteers", include_in_schema=False)
def update_volunteer_status_for_admin_alias(
    payload: UpdateStatusPayload,
    id: int = Query(..., ge=1),
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: CommunityService = Depends(get_community_service),
) -> dict[str, object]:
    return api_ok(service.update_volunteer_status(session, id, payload))
