from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_session_service
from app.core.response import api_ok
from app.services.session_service import SessionService


router = APIRouter(tags=["session"])


@router.get("/api/session")
def read_session(
    request: Request,
    service: SessionService = Depends(get_session_service),
) -> dict[str, object]:
    raw_user_cookie = request.cookies.get(service.settings.cookie_user_name)
    return api_ok(service.read_session(raw_user_cookie))


@router.post("/api/logout")
def logout(
    response: Response,
    service: SessionService = Depends(get_session_service),
) -> dict[str, object]:
    service.clear_auth_cookies(response)
    return api_ok()
