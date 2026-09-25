from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_public_read_cache, get_report_service, require_auth_context, require_privileged_auth_context
from app.api.routes.admin import _invalidate_admin_material_read_caches
from app.core.config import Settings, get_settings
from app.core.db import get_db_session
from app.core.public_read_cache import invalidate_prefixes
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.reports import AdminReportUpdatePayload, ReportCreatePayload
from app.services.report_service import ReportService, enforce_report_submit_rate_limit


router = APIRouter(tags=["reports"])


def _invalidate_report_target_cache(target_type: str) -> None:
    # Auto-hide (submit reaching the threshold) and admin restores flip a
    # material/comment/market item's visibility outside of its own mutation
    # endpoint; without this the anonymous read cache would keep serving the
    # stale (pre-hide or pre-restore) content until its TTL expires. Callers
    # only invoke this when the visibility actually changed (see
    # ReportService.submit_report/update_report's `hidden`/`restored`
    # results) -- invalidate_prefixes does a scan + delete on the Redis
    # backend, so it must not run on every report submission/restore
    # regardless of outcome.
    normalized = (target_type or "").strip().upper()
    if normalized == "MATERIAL":
        # Shares the same invalidation as admin material moderation, which
        # also covers the leaderboard contributor cache.
        _invalidate_admin_material_read_caches()
    elif normalized == "COMMENT":
        invalidate_prefixes(get_public_read_cache(), "comments", "materials:detail")
    elif normalized == "MARKET_ITEM":
        invalidate_prefixes(get_public_read_cache(), "market")


@router.post("/api/reports")
def submit_report(
    payload: ReportCreatePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: ReportService = Depends(get_report_service),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    enforce_report_submit_rate_limit(settings, user_id=auth.user_id or 0)
    entity, hidden = service.submit_report(
        session,
        reporter_id=auth.user_id or 0,
        target_type=payload.targetType,
        target_id=payload.targetId,
        reason=payload.reason,
    )
    if hidden:
        _invalidate_report_target_cache(payload.targetType)
    return api_ok({"id": entity.id})


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
    result, restored = service.update_report(session, id, payload)
    if restored:
        _invalidate_report_target_cache(result.get("targetType", ""))
    return api_ok(result)
