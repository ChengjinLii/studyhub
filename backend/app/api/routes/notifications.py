from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_notification_service, require_auth_context, require_privileged_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.notifications import NotificationCreatePayload
from app.services.notification_service import NotificationService


router = APIRouter(tags=["notifications"])


@router.get("/api/notifications/summary")
def notifications_summary(
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: NotificationService = Depends(get_notification_service),
) -> dict[str, object]:
    return api_ok(service.get_summary(session, auth.user_id or 0))


@router.get("/api/notifications")
@router.get("/api/notifications/list", include_in_schema=False)
def notifications_list(
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: NotificationService = Depends(get_notification_service),
) -> dict[str, object]:
    return api_ok(service.list_recent(session, auth.user_id or 0))


@router.patch("/api/notifications")
@router.post("/api/notifications/read", include_in_schema=False)
def mark_notifications_read(
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: NotificationService = Depends(get_notification_service),
) -> dict[str, object]:
    service.mark_all_read(session, auth.user_id or 0)
    return api_ok()


@router.post("/api/admin/notifications")
@router.post("/api/notifications/admin", include_in_schema=False)
def create_notification_for_admin(
    payload: NotificationCreatePayload,
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: NotificationService = Depends(get_notification_service),
) -> dict[str, object]:
    service.create_notification(session, admin_id=auth.user_id or 0, payload=payload)
    return api_ok()
