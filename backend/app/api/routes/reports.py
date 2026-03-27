from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_report_service, require_auth_context, require_privileged_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.reports import AdminReportUpdatePayload, ReportCreatePayload
from app.services.report_service import ReportService


router = APIRouter(tags=["reports"])


@router.post("/api/reports")
def submit_report(
    payload: ReportCreatePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: ReportService = Depends(get_report_service),
) -> dict[str, object]:
    return api_ok(service.submit(session, auth.user_id or 0, payload))


@router.get("/api/admin/reports")
def list_reports_for_admin(
    page: int = 0,
    size: int = 20,
    status: str | None = None,
    targetType: str | None = None,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: ReportService = Depends(get_report_service),
) -> dict[str, object]:
    return api_ok(service.list_for_admin(session, status_value=status, target_type=targetType, page=page, size=size))


@router.patch("/api/admin/reports/{id}")
def update_report_for_admin(
    id: int,
    payload: AdminReportUpdatePayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: ReportService = Depends(get_report_service),
) -> dict[str, object]:
    return api_ok(service.update_report(session, id, payload))
