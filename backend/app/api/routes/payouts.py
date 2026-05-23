from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    get_account_service,
    get_payout_service,
    require_auth_context,
    require_privileged_auth_context,
)
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.finance import (
    AdminMonthlyPayoutMarkPayload,
    PayoutApplicationCreatePayload,
    PayoutApplicationReviewPayload,
    PayoutScheduleUpdatePayload,
)
from app.services.account_service import AccountService
from app.services.payout_service import PayoutService


router = APIRouter(tags=["payouts"])


@router.post("/api/creator-payout-applications")
def create_payout_application(
    payload: PayoutApplicationCreatePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> dict[str, object]:
    return api_ok(service.create_application(session, user_id=auth.user_id or 0, payload=payload.model_dump()))


@router.get("/api/me/creator-payout-application")
@router.get("/api/creator-payout-applications/me", include_in_schema=False)
def get_my_payout_application(
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> dict[str, object]:
    return api_ok(service.get_latest_for_user(session, user_id=auth.user_id or 0))


@router.get("/api/admin/creator-payout-applications")
def list_payout_applications_for_admin(
    page: int = 0,
    size: int = 20,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> dict[str, object]:
    return api_ok(service.list_for_admin(session, page=page, size=size))


@router.patch("/api/admin/creator-payout-applications", include_in_schema=False)
def review_payout_application_alias(
    payload: PayoutApplicationReviewPayload,
    id: int = Query(..., ge=1),
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> dict[str, object]:
    return api_ok(
        service.review_application(
            session,
            admin_id=auth.user_id or 0,
            application_id=id,
            status_value=payload.status,
            review_notes=payload.reviewNotes,
        )
    )


@router.patch("/api/admin/creator-payout-applications/{id}")
def review_payout_application(
    id: int,
    payload: PayoutApplicationReviewPayload,
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> dict[str, object]:
    return api_ok(
        service.review_application(
            session,
            admin_id=auth.user_id or 0,
            application_id=id,
            status_value=payload.status,
            review_notes=payload.reviewNotes,
        )
    )


@router.get("/api/admin/creator-payout-applications/{id}/settlements")
@router.get("/api/admin/creator-payout-applications/{id}/details", include_in_schema=False)
def get_payout_application_details(
    id: int,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> dict[str, object]:
    return api_ok(service.list_settlement_details(session, application_id=id))


@router.get("/api/admin/payout-schedule")
def get_payout_schedule(
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> dict[str, object]:
    return api_ok(service.get_schedule(session))


@router.patch("/api/admin/payout-schedule")
def update_payout_schedule(
    payload: PayoutScheduleUpdatePayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> dict[str, object]:
    return api_ok(service.update_schedule(session, launch_date=payload.launchDate, next_payout_date=payload.nextPayoutDate))


@router.get("/api/admin/monthly-payout-overview")
def get_monthly_payout_overview(
    month: str | None = None,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> dict[str, object]:
    return api_ok(service.get_monthly_overview(session, month_key_raw=month))


@router.put("/api/admin/monthly-payout-marks")
@router.patch("/api/admin/monthly-payout-overview/marks", include_in_schema=False)
def mark_monthly_payout(
    payload: AdminMonthlyPayoutMarkPayload,
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> dict[str, object]:
    return api_ok(
        service.mark_monthly_payout(
            session,
            month_key=payload.monthKey,
            uploader_id=payload.uploaderId,
            mark_paid=payload.markPaid,
            admin_id=auth.user_id or 0,
        )
    )


@router.get("/api/admin/users/{uploaderId}/payout-qr")
@router.get("/api/admin/monthly-payout-overview/users/{uploaderId}/payout-qr", include_in_schema=False)
def get_admin_payout_qr(
    uploaderId: int,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> dict[str, object]:
    return api_ok(service.get_admin_payout_qr(session, uploader_id=uploaderId))


@router.post("/api/me/payout-qr")
def upload_my_payout_qr(
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    payout_service: PayoutService = Depends(get_payout_service),
    account_service: AccountService = Depends(get_account_service),
) -> dict[str, object]:
    payout_service.upload_payout_qr(session, user_id=auth.user_id or 0, upload=file)
    return api_ok(account_service.get_account(session, auth.user_id or 0))


@router.delete("/api/me/payout-qr")
def clear_my_payout_qr(
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    payout_service: PayoutService = Depends(get_payout_service),
    account_service: AccountService = Depends(get_account_service),
) -> dict[str, object]:
    payout_service.clear_payout_qr(session, user_id=auth.user_id or 0)
    return api_ok(account_service.get_account(session, auth.user_id or 0))


@router.get("/api/users/{id}/payout-qr/image")
def get_user_payout_qr_image(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> Response:
    path, media_type, direct_url = service.resolve_payout_qr_asset(
        session,
        target_user_id=id,
        viewer_user_id=auth.user_id or 0,
        viewer_role_mask=auth.role_mask,
    )
    if direct_url:
        return RedirectResponse(direct_url, status_code=307)
    if path is None:
        raise HTTPException(status_code=404, detail="收款码不存在")
    return FileResponse(path, media_type=media_type)
