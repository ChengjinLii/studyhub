from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import (
    get_optional_auth_context,
    get_public_read_cache,
    get_requests_service,
    require_auth_context,
    require_privileged_auth_context,
)
from app.core.db import get_db_session
from app.core.public_read_cache import PublicReadCache, cache_if_anonymous, invalidate_prefixes
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.requests import (
    RequestAcceptPayload,
    RequestArbitrationDecisionPayload,
    RequestContributionCreatePayload,
    RequestContributionDeadlinePayload,
    RequestCreatePayload,
    RequestDisputePayload,
    RequestPreviewViewPayload,
    RequestRespondPayload,
)
from app.services.requests_service import RequestsService


router = APIRouter(tags=["requests"])


@router.get("/api/requests")
def list_requests(
    sort: str | None = None,
    limit: int | None = None,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    cache: PublicReadCache = Depends(get_public_read_cache),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    current_user_id = auth.user_id if auth else None
    data = cache_if_anonymous(
        cache,
        current_user_id=current_user_id,
        namespace="requests:list",
        key=(sort, limit),
        factory=lambda: service.list_requests(session, current_user_id, sort=sort, limit=limit),
    )
    return api_ok(data)


@router.get("/api/requests/leaderboard")
def request_leaderboard(
    limit: int | None = None,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
    cache: PublicReadCache = Depends(get_public_read_cache),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    current_user_id = auth.user_id if auth else None
    data = cache_if_anonymous(
        cache,
        current_user_id=current_user_id,
        namespace="requests:leaderboard",
        key=(limit,),
        factory=lambda: service.list_leaderboard(session, current_user_id, limit=limit),
    )
    return api_ok(data)


@router.get("/api/requests/{id}")
def request_detail(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    return api_ok(service.get_detail(session, auth.user_id or 0, auth.role_mask, id))


@router.post("/api/requests")
def create_request(
    payload: RequestCreatePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    data = service.create_request(session, auth.user_id or 0, payload)
    _invalidate_request_read_caches()
    return api_ok(data)


@router.post("/api/requests/{id}/follow")
def follow_request(
    id: int,
    payload: RequestContributionCreatePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    data = service.follow_request(session, id, auth.user_id or 0, payload)
    _invalidate_request_read_caches()
    return api_ok(data)


@router.get("/api/requests/{id}/responses")
def request_responses(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    return api_ok(service.get_responses(session, auth.user_id or 0, auth.role_mask, id))


@router.get("/api/requests/{id}/contributions")
def request_contributions(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    return api_ok(service.get_contributions(session, auth.user_id or 0, auth.role_mask, id))


@router.get("/api/requests/contributions/status")
def request_contribution_status(
    orderNo: str,
    force: bool | None = None,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    return api_ok(service.get_contribution_status(session, orderNo, auth.user_id or 0, force_check=bool(force)))


@router.post("/api/requests/{id}/respond")
def request_respond(
    id: int,
    payload: RequestRespondPayload | None = None,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    data = service.respond(session, id, auth.user_id or 0, payload or RequestRespondPayload())
    _invalidate_request_read_caches()
    return api_ok(data)


@router.post("/api/requests/{id}/accept")
def request_accept(
    id: int,
    payload: RequestAcceptPayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    data = service.accept_response(session, id, auth.user_id or 0, auth.role_mask, payload)
    _invalidate_request_read_caches()
    return api_ok(data)


@router.post("/api/requests/{id}/preview-view")
def request_preview_view(
    id: int,
    payload: RequestPreviewViewPayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    service.record_preview_view(session, id, auth.user_id or 0, payload)
    _invalidate_request_read_caches()
    return api_ok()


@router.post("/api/requests/{id}/dispute")
def request_dispute(
    id: int,
    payload: RequestDisputePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    data = service.submit_dispute(session, id, auth.user_id or 0, payload)
    _invalidate_request_read_caches()
    return api_ok(data)


@router.post("/api/requests/arbitrations/{id}/decision")
def request_arbitration_decision(
    id: int,
    payload: RequestArbitrationDecisionPayload,
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    data = service.decide_arbitration(session, id, auth.user_id or 0, payload)
    _invalidate_request_read_caches()
    return api_ok(data)


@router.post("/api/requests/contributions/{id}/cancel")
def request_contribution_cancel(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    data = service.cancel_contribution(session, id, auth.user_id or 0)
    _invalidate_request_read_caches()
    return api_ok(data)


@router.put("/api/requests/contributions/{id}/deadline")
def request_contribution_deadline(
    id: int,
    payload: RequestContributionDeadlinePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: RequestsService = Depends(get_requests_service),
) -> dict[str, object]:
    data = service.update_contribution_deadline(session, id, auth.user_id or 0, payload)
    _invalidate_request_read_caches()
    return api_ok(data)


def _invalidate_request_read_caches() -> None:
    invalidate_prefixes(get_public_read_cache(), "requests")
